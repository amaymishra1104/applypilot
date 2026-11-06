import asyncio
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from db import db, utc_now_iso
import crypto
from server import app, get_cors_origins
import application_engine
from application_engine import (
    get_settings,
    is_within_send_window,
    is_email_suppressed,
    suppress_email,
    unsuppress_email,
    send_application,
    run_autopilot_cycle,
    run_reply_scan_cycle,
)
import routes_applications
from routes_applications import check_send_rate_limit, MAX_MANUAL_SENDS_PER_MINUTE
import routes_suppressions
from auth import OWNER_USER_ID, create_session_token, COOKIE_NAME


@pytest_asyncio.fixture(autouse=True)
async def cleanup_phase4_db():
    test_uid = "test_user_phase4"
    collections = (
        db.suppressions,
        db.job_applications,
        db.app_settings,
        db.gmail_connections,
        db.follow_ups,
        db.reply_scan_state,
        db.hr_contacts,
        db.application_events,
    )
    for col in collections:
        await col.delete_many({"user_id": test_uid})
    yield test_uid
    for col in collections:
        await col.delete_many({"user_id": test_uid})


# ---------------------------------------------------------------- Crypto & Security

def test_mandatory_encryption_key_validation():
    # Valid key should pass
    crypto.validate_encryption_key()

    # Missing key raises RuntimeError
    with patch.dict(os.environ, {"APP_ENCRYPTION_KEY": ""}):
        with pytest.raises(RuntimeError, match="APP_ENCRYPTION_KEY is required"):
            crypto.validate_encryption_key()

    # Invalid key raises RuntimeError
    with patch.dict(os.environ, {"APP_ENCRYPTION_KEY": "not-valid-base64"}):
        with pytest.raises(RuntimeError, match="Invalid APP_ENCRYPTION_KEY"):
            crypto.validate_encryption_key()


def test_encryption_decryption_and_no_plaintext_fallback():
    secret = "my_super_secret_oauth_token_12345"
    encrypted = crypto.encrypt(secret)
    assert encrypted != secret
    assert crypto.decrypt(encrypted) == secret

    # Tampered ciphertext must raise ValueError, not return plaintext
    with pytest.raises(ValueError, match="Decryption failed"):
        crypto.decrypt("gAAAAABtampered_ciphertext_xyz")


def test_cors_origins_wildcard_rejection():
    with patch.dict(os.environ, {"CORS_ORIGINS": "*"}):
        origins = get_cors_origins()
        assert "*" not in origins
        assert "http://localhost:3000" in origins

    with patch.dict(os.environ, {"CORS_ORIGINS": "https://myapp.dev, http://localhost:3000"}):
        origins = get_cors_origins()
        assert "https://myapp.dev" in origins
        assert "http://localhost:3000" in origins


@pytest.mark.asyncio
async def test_manual_send_rate_limiting():
    # Reset rate timestamps
    routes_applications._send_timestamps.clear()

    # First MAX_MANUAL_SENDS_PER_MINUTE calls succeed
    for _ in range(MAX_MANUAL_SENDS_PER_MINUTE):
        await check_send_rate_limit()

    # 16th call within 60s raises HTTP 429
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await check_send_rate_limit()
    assert exc_info.value.status_code == 429
    assert "Too many send requests" in exc_info.value.detail

    routes_applications._send_timestamps.clear()


# ---------------------------------------------------------------- Send Window Rules

def test_is_within_send_window_logic():
    settings = {
        "autopilot": {
            "send_window": {
                "enabled": True,
                "timezone": "Asia/Kolkata",
                "start_hour": 9,
                "end_hour": 18,
                "days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
            }
        }
    }

    # Wednesday at 14:30 IST (inside)
    from zoneinfo import ZoneInfo
    tz_kolkata = ZoneInfo("Asia/Kolkata")
    wed_inside = datetime(2026, 11, 4, 14, 30, tzinfo=tz_kolkata)
    ok, reason = is_within_send_window(settings, wed_inside)
    assert ok is True
    assert "Within" in reason

    # Wednesday at 20:30 IST (outside hours)
    wed_late = datetime(2026, 11, 4, 20, 30, tzinfo=tz_kolkata)
    ok, reason = is_within_send_window(settings, wed_late)
    assert ok is False
    assert "Outside" in reason

    # Sunday at 14:30 IST (outside days)
    sun_noon = datetime(2026, 11, 8, 14, 30, tzinfo=tz_kolkata)
    ok, reason = is_within_send_window(settings, sun_noon)
    assert ok is False
    assert "Sun not in" in reason

    # Disabled window
    settings_disabled = {"autopilot": {"send_window": {"enabled": False}}}
    ok, _ = is_within_send_window(settings_disabled, sun_noon)
    assert ok is True


@pytest.mark.asyncio
async def test_autopilot_skips_outside_send_window(cleanup_phase4_db):
    test_uid = cleanup_phase4_db
    # Setup autopilot settings with window that excludes current time
    await db.app_settings.update_one(
        {"user_id": test_uid},
        {"$set": {
            "autopilot": {
                "enabled": True,
                "paused": False,
                "mode": "auto",
                "max_per_day": 10,
                "min_delay_minutes": 1,
                "min_match_score": 50,
                "send_window": {
                    "enabled": True,
                    "timezone": "UTC",
                    "start_hour": 1,
                    "end_hour": 2,  # Window 01:00 - 02:00 UTC
                    "days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
                }
            }
        }},
        upsert=True,
    )
    # Connected gmail
    await db.gmail_connections.update_one(
        {"user_id": test_uid},
        {"$set": {"email": "test@gmail.com", "status": "connected"}},
        upsert=True,
    )

    # Autopilot cycle with current time mocked outside 1-2 UTC
    with patch("application_engine.is_within_send_window", return_value=(False, "Outside test window")):
        summary = await run_autopilot_cycle(test_uid)
        assert summary["skipped"] == 1
        assert summary["sent"] == 0


# ---------------------------------------------------------------- Cross-Role Cooling-Off

@pytest.mark.asyncio
async def test_cross_role_cooldown_blocks_different_role_and_allows_force_send(cleanup_phase4_db):
    test_uid = cleanup_phase4_db
    hr_email = "recruiter@techcorp.com"

    # Set up settings with 14 day cooldown
    await db.app_settings.update_one(
        {"user_id": test_uid},
        {"$set": {
            "autopilot": {"cross_role_cooldown_days": 14, "max_per_day": 15, "min_delay_minutes": 10}
        }},
        upsert=True,
    )
    await db.gmail_connections.update_one(
        {"user_id": test_uid},
        {"$set": {"email": "test@gmail.com", "status": "connected"}},
        upsert=True,
    )

    # 1. Existing sent application 3 days ago for "Frontend Engineer"
    sent_3_days_ago = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    await db.job_applications.insert_one({
        "id": "app_prev_sent",
        "user_id": test_uid,
        "hr_email": hr_email,
        "company": "TechCorp",
        "job_title": "Frontend Engineer",
        "status": "sent",
        "sent_at": sent_3_days_ago,
        "dry_run": False,
    })

    # 2. New application for "Backend Engineer" to same recruiter
    new_app = {
        "id": "app_new_candidate",
        "user_id": test_uid,
        "hr_email": hr_email,
        "company": "TechCorp",
        "job_title": "Backend Engineer",
        "subject": "Application for Backend Engineer",
        "body_text": "Hi Recruiter",
        "attachment_path": "resumes/resume.pdf",
        "status": "approved",
    }
    await db.job_applications.insert_one(new_app.copy())

    # Send should be blocked by cross-role cooldown
    result = await send_application(test_uid, new_app, trigger="manual")
    assert result["ok"] is False
    assert "Cross-role cooldown active" in result["error"]
    assert "Cooling off period: 14 days" in result["error"]

    # Reset status in DB to approved for the retry
    await db.job_applications.update_one({"id": new_app["id"]}, {"$set": {"status": "approved"}})
    new_app["status"] = "approved"
    new_app["force_send"] = True
    with patch("application_engine.get_object", return_value=(b"%PDF-1.4 test", "application/pdf")), \
         patch("application_engine.is_dry_run", return_value=True):
        force_result = await send_application(test_uid, new_app, trigger="manual")
        assert force_result["ok"] is True


# ---------------------------------------------------------------- Bounces & Suppressions

@pytest.mark.asyncio
async def test_bounce_handling_auto_suppresses_and_cancels_followups(cleanup_phase4_db):
    test_uid = cleanup_phase4_db
    target_email = "bounced_candidate@domain.com"
    thread_id = "thread_bounce_123"

    # Sent application
    await db.job_applications.insert_one({
        "id": "app_bounced_1",
        "user_id": test_uid,
        "hr_email": target_email,
        "company": "BadDomain",
        "job_title": "DevOps",
        "thread_id": thread_id,
        "status": "sent",
        "sent_at": utc_now_iso(),
        "dry_run": False,
    })

    # Pending follow-up
    await db.follow_ups.insert_one({
        "id": "fu_1",
        "user_id": test_uid,
        "application_id": "app_bounced_1",
        "status": "pending",
        "due_at": utc_now_iso(),
    })

    # Connected gmail
    await db.gmail_connections.update_one(
        {"user_id": test_uid},
        {"$set": {"email": "sender@gmail.com", "status": "connected"}},
        upsert=True,
    )

    # Mock bounce message from mailer-daemon
    mock_messages = [{
        "id": "msg_bounce_999",
        "thread_id": thread_id,
        "from": "mailer-daemon@googlemail.com",
        "subject": "Delivery Status Notification (Failure)",
    }]

    with patch("gmail_service.list_recent_inbox", AsyncMock(return_value=mock_messages)), \
         patch("gmail_service.get_message_text", AsyncMock(return_value="550 5.1.1 The email account that you tried to reach does not exist.")), \
         patch("ai_service.classify_reply", AsyncMock(return_value={"category": "bounce", "summary": "Mailbox not found", "next_action": "Do not send"})):
        
        summary = await run_reply_scan_cycle(test_uid)
        assert summary["scanned"] == 1
        assert summary["replies"] == 1

    # Verify application marked as bounced
    app_doc = await db.job_applications.find_one({"id": "app_bounced_1"})
    assert app_doc["status"] == "bounced"
    assert app_doc.get("bounced") is True

    # Verify follow-up cancelled
    fu = await db.follow_ups.find_one({"id": "fu_1"})
    assert fu["status"] == "cancelled"

    # Verify target email automatically added to suppressions
    assert await is_email_suppressed(test_uid, target_email) is True
    sup = await db.suppressions.find_one({"user_id": test_uid, "email": target_email})
    assert sup["reason"] == "bounce"
    assert sup["source"] == "reply_scan"


@pytest.mark.asyncio
async def test_unsubscribe_auto_suppresses_and_cancels_followups(cleanup_phase4_db):
    test_uid = cleanup_phase4_db
    target_email = "unsub_recruiter@company.com"
    thread_id = "thread_unsub_456"

    await db.job_applications.insert_one({
        "id": "app_unsub_1",
        "user_id": test_uid,
        "hr_email": target_email,
        "company": "Corp",
        "job_title": "Engineer",
        "thread_id": thread_id,
        "status": "sent",
        "sent_at": utc_now_iso(),
        "dry_run": False,
    })
    await db.follow_ups.insert_one({
        "id": "fu_2",
        "user_id": test_uid,
        "application_id": "app_unsub_1",
        "status": "pending",
        "due_at": utc_now_iso(),
    })
    await db.gmail_connections.update_one(
        {"user_id": test_uid},
        {"$set": {"email": "sender@gmail.com", "status": "connected"}},
        upsert=True,
    )

    mock_messages = [{
        "id": "msg_unsub_123",
        "thread_id": thread_id,
        "from": target_email,
        "subject": "Please remove me from your list",
    }]

    with patch("gmail_service.list_recent_inbox", AsyncMock(return_value=mock_messages)), \
         patch("gmail_service.get_message_text", AsyncMock(return_value="Please unsubscribe me and stop emailing me.")), \
         patch("ai_service.classify_reply", AsyncMock(return_value={"category": "unsubscribe", "summary": "Recipient requested unsubscribe", "next_action": "Remove"})):
        
        summary = await run_reply_scan_cycle(test_uid)
        assert summary["scanned"] == 1

    app_doc = await db.job_applications.find_one({"id": "app_unsub_1"})
    assert app_doc["status"] == "unsubscribed"

    fu = await db.follow_ups.find_one({"id": "fu_2"})
    assert fu["status"] == "cancelled"

    assert await is_email_suppressed(test_uid, target_email) is True


@pytest.mark.asyncio
async def test_out_of_office_leaves_status_intact(cleanup_phase4_db):
    test_uid = cleanup_phase4_db
    target_email = "vacation_recruiter@company.com"
    thread_id = "thread_ooo_789"

    await db.job_applications.insert_one({
        "id": "app_ooo_1",
        "user_id": test_uid,
        "hr_email": target_email,
        "company": "Corp",
        "job_title": "Engineer",
        "thread_id": thread_id,
        "status": "sent",
        "sent_at": utc_now_iso(),
        "dry_run": False,
    })
    await db.gmail_connections.update_one(
        {"user_id": test_uid},
        {"$set": {"email": "sender@gmail.com", "status": "connected"}},
        upsert=True,
    )

    mock_messages = [{
        "id": "msg_ooo_123",
        "thread_id": thread_id,
        "from": target_email,
        "subject": "Automatic reply: Out of Office",
    }]

    with patch("gmail_service.list_recent_inbox", AsyncMock(return_value=mock_messages)), \
         patch("gmail_service.get_message_text", AsyncMock(return_value="I am on vacation until Nov 20.")), \
         patch("ai_service.classify_reply", AsyncMock(return_value={"category": "out_of_office", "summary": "Away until Nov 20", "next_action": "Wait"})):
        
        await run_reply_scan_cycle(test_uid)

    app_doc = await db.job_applications.find_one({"id": "app_ooo_1"})
    # Status remains 'sent'
    assert app_doc["status"] == "sent"
    # Not suppressed
    assert await is_email_suppressed(test_uid, target_email) is False
    # Event recorded
    event = await db.application_events.find_one({"user_id": test_uid, "application_id": "app_ooo_1", "type": "out_of_office"})
    assert event is not None


# ---------------------------------------------------------------- Suppression Enforcement & API

@pytest.mark.asyncio
async def test_suppressed_email_blocked_from_sending_and_contact_creation(cleanup_phase4_db):
    test_uid = cleanup_phase4_db
    suppressed_email = "do_not_email@example.com"
    await suppress_email(test_uid, suppressed_email, reason="manual_test", source="test")
    await suppress_email(OWNER_USER_ID, suppressed_email, reason="manual_test", source="test")

    try:
        # Send application to suppressed email fails
        app_doc = {
            "id": "app_sup_test",
            "user_id": test_uid,
            "hr_email": suppressed_email,
            "company": "Example",
            "job_title": "Developer",
            "status": "approved",
        }
        await db.job_applications.insert_one(app_doc.copy())
        res = await send_application(test_uid, app_doc, trigger="manual")
        assert res["ok"] is False
        assert "suppressed" in res["error"]

        # Contact creation endpoint rejects suppressed email
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = create_session_token(OWNER_USER_ID)
            client.cookies.set(COOKIE_NAME, token)

            contact_res = await client.post(
                "/api/contacts",
                json={"hr_email": suppressed_email, "hr_name": "Bob", "company_name": "TestCorp"},
            )
            assert contact_res.status_code == 400
            assert "suppression list" in contact_res.json()["detail"]
    finally:
        await unsuppress_email(OWNER_USER_ID, suppressed_email)


@pytest.mark.asyncio
async def test_suppression_crud_endpoints(cleanup_phase4_db):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token = create_session_token(OWNER_USER_ID)
        client.cookies.set(COOKIE_NAME, token)

        # 1. Add email to suppression list
        add_res = await client.post(
            "/api/suppressions",
            json={"email": "bad_contact@spam.org", "reason": "requested_removal"},
        )
        assert add_res.status_code == 200
        data = add_res.json()
        assert data["email"] == "bad_contact@spam.org"
        assert data["reason"] == "requested_removal"

        # 2. List suppressions
        list_res = await client.get("/api/suppressions")
        assert list_res.status_code == 200
        emails = [s["email"] for s in list_res.json()]
        assert "bad_contact@spam.org" in emails

        # 3. Remove from suppression list
        del_res = await client.delete("/api/suppressions/bad_contact@spam.org")
        assert del_res.status_code == 200
        assert del_res.json()["ok"] is True

        # Verify no longer suppressed
        list_res2 = await client.get("/api/suppressions")
        emails2 = [s["email"] for s in list_res2.json()]
        assert "bad_contact@spam.org" not in emails2


# ---------------------------------------------------------------- Settings Preservation

@pytest.mark.asyncio
async def test_settings_preserves_shape_and_updates_deliverability(cleanup_phase4_db):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token = create_session_token(OWNER_USER_ID)
        client.cookies.set(COOKIE_NAME, token)

        # Initial GET
        get_res = await client.get("/api/settings")
        assert get_res.status_code == 200
        initial_data = get_res.json()
        assert "autopilot" in initial_data
        assert "send_window" in initial_data["autopilot"]

        # PUT deliverability update
        put_payload = {
            "autopilot": {
                "max_per_day": 20,
                "jitter_seconds": 45,
                "cross_role_cooldown_days": 21,
                "send_window": {
                    "enabled": True,
                    "timezone": "Asia/Kolkata",
                    "start_hour": 10,
                    "end_hour": 17,
                    "days": ["Mon", "Tue", "Wed", "Thu"],
                }
            }
        }
        put_res = await client.put("/api/settings", json=put_payload)
        assert put_res.status_code == 200
        updated = put_res.json()

        # Check values were updated
        assert updated["autopilot"]["max_per_day"] == 20
        assert updated["autopilot"]["jitter_seconds"] == 45
        assert updated["autopilot"]["cross_role_cooldown_days"] == 21
        assert updated["autopilot"]["send_window"]["start_hour"] == 10
        assert updated["autopilot"]["send_window"]["end_hour"] == 17
        assert updated["autopilot"]["send_window"]["days"] == ["Mon", "Tue", "Wed", "Thu"]

        # Check existing fields were NOT wiped
        assert "profile" in updated
        assert "followups" in updated
        assert "notifications" in updated
