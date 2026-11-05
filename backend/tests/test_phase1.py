import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
import pytest_asyncio
from google.auth.exceptions import RefreshError

from db import db, utc_now_iso
from crypto import encrypt
import gmail_service
import application_engine


@pytest_asyncio.fixture(autouse=True)
async def cleanup_db():
    test_uid = "test_user_phase1"
    await db.gmail_connections.delete_many({"user_id": test_uid})
    await db.job_applications.delete_many({"user_id": test_uid})
    await db.app_settings.delete_many({"user_id": test_uid})
    await db.google_oauth_config.delete_many({"user_id": test_uid})
    yield test_uid
    await db.gmail_connections.delete_many({"user_id": test_uid})
    await db.job_applications.delete_many({"user_id": test_uid})
    await db.app_settings.delete_many({"user_id": test_uid})
    await db.google_oauth_config.delete_many({"user_id": test_uid})


@pytest.mark.asyncio
async def test_gmail_refresh_failure_marks_reauth_required(cleanup_db):
    uid = cleanup_db
    # Seed connection with expired token
    expired_at = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    await db.gmail_connections.insert_one({
        "user_id": uid,
        "email": "user@gmail.com",
        "access_token": encrypt("old_token"),
        "refresh_token": encrypt("my_refresh_token"),
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "test_client_id",
        "expires_at": expired_at,
        "status": "connected",
    })
    await db.google_oauth_config.insert_one({
        "user_id": uid,
        "client_id": encrypt("test_client_id"),
        "client_secret": encrypt("test_secret"),
    })

    # Mock Refresh to raise RefreshError (Google rejected refresh token)
    with patch("google.oauth2.credentials.Credentials.refresh", side_effect=RefreshError("invalid_grant: Token has been expired or revoked.")):
        creds = await gmail_service.get_creds(uid)
        assert creds is None

    conn = await db.gmail_connections.find_one({"user_id": uid})
    assert conn["status"] == "reauth_required"
    assert "invalid_grant" in conn["last_refresh_error"]


@pytest.mark.asyncio
async def test_gmail_network_error_does_not_mark_reauth_required(cleanup_db):
    uid = cleanup_db
    expired_at = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    await db.gmail_connections.insert_one({
        "user_id": uid,
        "email": "user@gmail.com",
        "access_token": encrypt("old_token"),
        "refresh_token": encrypt("my_refresh_token"),
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "test_client_id",
        "expires_at": expired_at,
        "status": "connected",
    })
    await db.google_oauth_config.insert_one({
        "user_id": uid,
        "client_id": encrypt("test_client_id"),
        "client_secret": encrypt("test_secret"),
    })

    # Mock Refresh to raise a network Timeout
    with patch("google.oauth2.credentials.Credentials.refresh", side_effect=ConnectionError("Network connection reset")):
        creds = await gmail_service.get_creds(uid)
        assert creds is None

    conn = await db.gmail_connections.find_one({"user_id": uid})
    # Status should still be connected, NOT reauth_required
    assert conn["status"] == "connected"


@pytest.mark.asyncio
async def test_autopilot_skips_reauth_required_users(cleanup_db):
    uid = cleanup_db
    await db.gmail_connections.insert_one({
        "user_id": uid,
        "email": "user@gmail.com",
        "status": "reauth_required",
    })
    await db.app_settings.insert_one({
        "user_id": uid,
        "autopilot": {"enabled": True, "paused": False, "mode": "approval", "max_per_day": 10, "min_delay_minutes": 0},
    })
    await db.job_applications.insert_one({
        "id": "app_reauth_1",
        "user_id": uid,
        "status": "approved",
        "company": "Acme",
        "hr_email": "hr@acme.com",
        "subject": "Hello",
        "match_score": 90,
        "created_at": utc_now_iso(),
    })

    summary = await application_engine.run_autopilot_cycle(uid)
    assert summary["sent"] == 0
    assert summary["skipped"] >= 1

    app = await db.job_applications.find_one({"id": "app_reauth_1"})
    assert app["status"] == "approved"  # Not touched, not failed


@pytest.mark.asyncio
async def test_approved_app_below_min_score_still_sends(cleanup_db):
    uid = cleanup_db
    await db.gmail_connections.insert_one({
        "user_id": uid,
        "email": "user@gmail.com",
        "status": "connected",
    })
    await db.app_settings.insert_one({
        "user_id": uid,
        "autopilot": {
            "enabled": True, "paused": False, "mode": "approval",
            "max_per_day": 10, "min_delay_minutes": 0, "min_match_score": 80,
        },
    })
    # Application has score 50 (below min 80), but was manually approved
    await db.job_applications.insert_one({
        "id": "app_approved_low_score",
        "user_id": uid,
        "status": "approved",
        "company": "Acme",
        "hr_email": "hr@acme.com",
        "subject": "Application",
        "body_text": "Cover letter text",
        "attachment_path": "resumes/test.pdf",
        "match_score": 50,
        "created_at": utc_now_iso(),
    })

    with patch("gmail_service.send_gmail_email", new=AsyncMock(return_value=("msg_123", "thread_123"))), \
         patch("application_engine.get_object", return_value=(b"%PDF-test", "test.pdf")):
        summary = await application_engine.run_autopilot_cycle(uid)

    assert summary["sent"] == 1
    app = await db.job_applications.find_one({"id": "app_approved_low_score"})
    assert app["status"] == "sent"
    assert app["message_id"] == "msg_123"


@pytest.mark.asyncio
async def test_queued_auto_below_min_score_is_skipped(cleanup_db):
    uid = cleanup_db
    await db.gmail_connections.insert_one({
        "user_id": uid,
        "email": "user@gmail.com",
        "status": "connected",
    })
    await db.app_settings.insert_one({
        "user_id": uid,
        "autopilot": {
            "enabled": True, "paused": False, "mode": "auto",
            "max_per_day": 10, "min_delay_minutes": 0, "min_match_score": 80,
        },
    })
    await db.job_applications.insert_one({
        "id": "app_queued_low_score",
        "user_id": uid,
        "status": "queued_auto",
        "company": "Acme",
        "hr_email": "hr@acme.com",
        "subject": "Application",
        "body_text": "Cover letter text",
        "attachment_path": "resumes/test.pdf",
        "match_score": 50,  # Below min 80
        "created_at": utc_now_iso(),
    })

    with patch("gmail_service.send_gmail_email", new=AsyncMock(return_value=("msg_123", "thread_123"))), \
         patch("application_engine.get_object", return_value=(b"%PDF-test", "test.pdf")):
        summary = await application_engine.run_autopilot_cycle(uid)

    assert summary["sent"] == 0
    app = await db.job_applications.find_one({"id": "app_queued_low_score"})
    assert app["status"] == "queued_auto"  # Still queued, not sent


@pytest.mark.asyncio
async def test_concurrent_sends_only_one_gmail_call(cleanup_db):
    uid = cleanup_db
    await db.gmail_connections.insert_one({
        "user_id": uid,
        "email": "user@gmail.com",
        "status": "connected",
    })
    await db.app_settings.insert_one({
        "user_id": uid,
        "autopilot": {"enabled": True, "paused": False, "mode": "auto", "max_per_day": 10, "min_delay_minutes": 0},
    })
    app_doc = {
        "id": "app_concurrent_test",
        "user_id": uid,
        "status": "approved",
        "company": "Acme",
        "hr_email": "hr@acme.com",
        "subject": "Application",
        "body_text": "Cover letter text",
        "attachment_path": "resumes/test.pdf",
        "match_score": 90,
        "created_at": utc_now_iso(),
    }
    await db.job_applications.insert_one(app_doc)

    gmail_mock = AsyncMock(return_value=("msg_concurrent", "thread_concurrent"))

    async def delayed_send(*args, **kwargs):
        await asyncio.sleep(0.05)
        return await gmail_mock(*args, **kwargs)

    with patch("gmail_service.send_gmail_email", side_effect=delayed_send), \
         patch("application_engine.get_object", return_value=(b"%PDF-test", "test.pdf")):
        # Launch two sends of the exact same application simultaneously
        res1, res2 = await asyncio.gather(
            application_engine.send_application(uid, app_doc, trigger="worker_1"),
            application_engine.send_application(uid, app_doc, trigger="worker_2"),
        )

    # Exactly one should succeed, the other should be rejected by the atomic claim
    results = [res1["ok"], res2["ok"]]
    assert results.count(True) == 1
    assert results.count(False) == 1
    assert gmail_mock.call_count == 1

    app = await db.job_applications.find_one({"id": "app_concurrent_test"})
    assert app["status"] == "sent"
    assert app["message_id"] == "msg_concurrent"


@pytest.mark.asyncio
async def test_stale_sending_recovered_to_needs_attention(cleanup_db):
    uid = cleanup_db
    stale_time = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
    await db.job_applications.insert_one({
        "id": "app_stuck_sending",
        "user_id": uid,
        "status": "sending",
        "sending_at": stale_time,
        "previous_status": "approved",
        "company": "Acme",
        "hr_email": "hr@acme.com",
        "created_at": stale_time,
    })

    recovered = await application_engine.cleanup_stuck_sending_applications(uid)
    assert recovered == 1

    app = await db.job_applications.find_one({"id": "app_stuck_sending"})
    assert app["status"] == "needs_attention"
    assert "Gmail Sent folder" in app["error"]


@pytest.mark.asyncio
async def test_retry_handling_restores_previous_status_until_max_retries(cleanup_db):
    uid = cleanup_db
    await db.gmail_connections.insert_one({
        "user_id": uid,
        "email": "user@gmail.com",
        "status": "connected",
    })
    await db.app_settings.insert_one({
        "user_id": uid,
        "autopilot": {"enabled": True, "paused": False, "mode": "auto", "max_per_day": 10, "min_delay_minutes": 0, "max_retries": 2},
    })
    app_doc = {
        "id": "app_retry_test",
        "user_id": uid,
        "status": "approved",
        "retries": 0,
        "company": "Acme",
        "hr_email": "hr@acme.com",
        "subject": "Application",
        "body_text": "Text",
        "attachment_path": "resumes/test.pdf",
        "created_at": utc_now_iso(),
    }
    await db.job_applications.insert_one(app_doc)

    # First send attempt fails: retries becomes 1 < 2, so status is restored to "approved"
    with patch("gmail_service.send_gmail_email", side_effect=RuntimeError("SMTP temporary error")), \
         patch("application_engine.get_object", return_value=(b"%PDF-test", "test.pdf")):
        res1 = await application_engine.send_application(uid, app_doc, trigger="auto-pilot")

    assert res1["ok"] is False
    assert res1["status"] == "approved"
    assert res1["retries"] == 1

    app = await db.job_applications.find_one({"id": "app_retry_test"})
    assert app["status"] == "approved"
    assert app["retries"] == 1

    # Second send attempt fails: retries becomes 2 >= 2, so status is "send_failed"
    with patch("gmail_service.send_gmail_email", side_effect=RuntimeError("SMTP fatal error")), \
         patch("application_engine.get_object", return_value=(b"%PDF-test", "test.pdf")):
        res2 = await application_engine.send_application(uid, app, trigger="auto-pilot")

    assert res2["ok"] is False
    assert res2["status"] == "send_failed"
    assert res2["retries"] == 2

    app = await db.job_applications.find_one({"id": "app_retry_test"})
    assert app["status"] == "send_failed"
    assert app["retries"] == 2


@pytest.mark.asyncio
async def test_generate_application_auto_confirms_match_in_auto_mode(cleanup_db):
    from routes_applications import generate_application, GenerateIn
    uid = cleanup_db

    # Seed role profile, active resume, opportunity, and unconfirmed match
    await db.role_profiles.insert_one({
        "id": "role_1",
        "user_id": uid,
        "title": "Software Engineer",
        "skills": ["Python", "FastAPI"],
    })
    await db.resume_versions.insert_one({
        "id": "res_1",
        "user_id": uid,
        "role_profile_id": "role_1",
        "version_no": 1,
        "name": "Software Engineer v1",
        "storage_path": "resumes/resume.pdf",
        "filename": "resume.pdf",
        "active": True,
    })
    await db.hr_contacts.insert_one({
        "id": "contact_1",
        "user_id": uid,
        "company_name": "Tech Corp",
        "hr_name": "Jane Recruiter",
        "hr_email": "jane@techcorp.com",
    })
    await db.job_opportunities.insert_one({
        "id": "opp_1",
        "user_id": uid,
        "company_name": "Tech Corp",
        "job_title": "Backend Developer",
        "hr_contact_id": "contact_1",
    })
    await db.job_matches.insert_one({
        "id": "match_1",
        "user_id": uid,
        "opportunity_id": "opp_1",
        "role_profile_id": "role_1",
        "resume_version_id": "res_1",
        "score": 85,
        "confirmed": False,
    })
    await db.app_settings.insert_one({
        "user_id": uid,
        "autopilot": {"enabled": True, "paused": False, "mode": "auto", "min_match_score": 70},
    })

    with patch("ai_service.generate_application_email", new=AsyncMock(return_value={"subject": "Apply", "body": "Letter"})):
        app = await generate_application(
            body=GenerateIn(opportunity_id="opp_1"),
            user={"user_id": uid, "name": "Candidate"},
        )

    # In auto mode with score 85 >= 70, status must be queued_auto
    assert app["status"] == "queued_auto"

    # Match in database must be auto-confirmed
    match = await db.job_matches.find_one({"id": "match_1"})
    assert match["confirmed"] is True

