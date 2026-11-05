import asyncio
import os
import sys
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
import pytest_asyncio
from db import db, utc_now_iso
import application_engine
import gmail_service
import routes_applications


@pytest_asyncio.fixture(autouse=True)
async def cleanup_test_db():
    test_uid = "test_user_dry_isolation"
    await db.job_applications.delete_many({"user_id": test_uid})
    await db.app_settings.delete_many({"user_id": test_uid})
    await db.gmail_connections.delete_many({"user_id": test_uid})
    await db.hr_contacts.delete_many({"user_id": test_uid})
    await db.opportunities.delete_many({"user_id": test_uid})
    await db.follow_ups.delete_many({"user_id": test_uid})
    await db.application_events.delete_many({"user_id": test_uid})
    yield
    await db.job_applications.delete_many({"user_id": test_uid})
    await db.app_settings.delete_many({"user_id": test_uid})
    await db.gmail_connections.delete_many({"user_id": test_uid})
    await db.hr_contacts.delete_many({"user_id": test_uid})
    await db.opportunities.delete_many({"user_id": test_uid})
    await db.follow_ups.delete_many({"user_id": test_uid})
    await db.application_events.delete_many({"user_id": test_uid})


@pytest.mark.asyncio
async def test_dry_run_does_not_block_real_generation_or_send(monkeypatch):
    uid = "test_user_dry_isolation"
    email = "recruiter@techcorp.io"
    role = "Senior Python Engineer"

    # 1. Insert a dry-run application that was previously simulated as "sent"
    await db.job_applications.insert_one({
        "id": "app_dry_sent_1",
        "user_id": uid,
        "hr_email": email,
        "job_title": role,
        "job_title_norm": "senior python engineer",
        "status": "sent",
        "dry_run": True,
        "sent_at": datetime.now(timezone.utc).isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    # Verify duplicate_application_exists returns False for real operations
    is_dup = await application_engine.duplicate_application_exists(uid, email, role)
    assert is_dup is False, "Dry-run application must not trigger duplicate detection for real operations"

    # Setup Gmail connection and settings
    await db.gmail_connections.insert_one({
        "user_id": uid,
        "email": "user@gmail.com",
        "status": "connected",
        "refresh_token": "valid_refresh",
    })
    await db.app_settings.insert_one({
        "user_id": uid,
        "autopilot": {"max_retries": 2},
    })

    # Create real application document
    real_app = {
        "id": "app_real_2",
        "user_id": uid,
        "hr_email": email,
        "job_title": role,
        "job_title_norm": "senior python engineer",
        "subject": "Application for Senior Python Engineer",
        "body_text": "Dear Recruiter,\n\nI am writing to apply for the Senior Python Engineer role.",
        "status": "approved",
        "dry_run": False,
        "attachment_path": "resumes/resume.pdf",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.job_applications.insert_one(real_app)

    # Disable DRY_RUN to test real send path
    monkeypatch.setenv("DRY_RUN", "false")
    assert application_engine.is_dry_run() is False

    mock_send = AsyncMock(return_value=("msg_real_12345", "th_real_12345"))
    with patch.object(gmail_service, "send_gmail_email", mock_send), \
         patch("application_engine.get_object", return_value=(b"%PDF-real", "resume.pdf")):
        res = await application_engine.send_application(uid, real_app, trigger="manual", allowed_statuses=["approved"])

    assert res["ok"] is True
    assert res["message_id"] == "msg_real_12345"
    mock_send.assert_awaited_once()

    # Verify real app is marked sent without dry_run=True
    saved = await db.job_applications.find_one({"id": "app_real_2"})
    assert saved["status"] == "sent"
    assert saved.get("dry_run") is not True
    assert saved["message_id"] == "msg_real_12345"


@pytest.mark.asyncio
async def test_dry_run_ignored_by_reply_scan():
    uid = "test_user_dry_isolation"
    await db.gmail_connections.insert_one({
        "user_id": uid,
        "email": "user@gmail.com",
        "status": "connected",
    })
    # Dry-run application with status "sent"
    await db.job_applications.insert_one({
        "id": "app_dry_reply",
        "user_id": uid,
        "hr_email": "hr@partner.com",
        "thread_id": "thread_dry_123",
        "status": "sent",
        "dry_run": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    # Mock inbox returning message for this dry thread
    inbox_msg = [{
        "id": "msg_reply_1",
        "thread_id": "thread_dry_123",
        "from": "HR <hr@partner.com>",
        "subject": "Re: Application",
    }]
    with patch.object(gmail_service, "list_recent_inbox", AsyncMock(return_value=inbox_msg)), \
         patch.object(gmail_service, "get_message_text", AsyncMock(return_value="Let's interview!")):
        summary = await application_engine.run_reply_scan_cycle(uid)

    # Dry-run application was excluded from candidates, so scanned is 0
    assert summary["scanned"] == 0
    assert summary["replies"] == 0
    app = await db.job_applications.find_one({"id": "app_dry_reply"})
    assert app["status"] == "sent"


@pytest.mark.asyncio
async def test_dry_run_ignored_by_followup_cycle():
    uid = "test_user_dry_isolation"
    await db.gmail_connections.insert_one({
        "user_id": uid,
        "email": "user@gmail.com",
        "status": "connected",
    })
    await db.app_settings.insert_one({
        "user_id": uid,
        "followups": {"enabled": True, "days": 3},
    })
    past_date = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    await db.job_applications.insert_one({
        "id": "app_dry_followup",
        "user_id": uid,
        "hr_email": "lead@target.com",
        "company": "TargetCo",
        "job_title": "DevOps",
        "status": "sent",
        "sent_at": past_date,
        "dry_run": True,
    })

    summary = await application_engine.run_followup_cycle(uid)
    assert summary["created"] == 0
    count_followups = await db.follow_ups.count_documents({"application_id": "app_dry_followup"})
    assert count_followups == 0


@pytest.mark.asyncio
async def test_dry_run_ignored_by_interview_reminders():
    uid = "test_user_dry_isolation"
    tomorrow = (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat()
    await db.app_settings.insert_one({
        "user_id": uid,
        "interviews": {"reminder_hours": 24},
        "notifications": {"interview_reminder": True},
    })
    await db.job_applications.insert_one({
        "id": "app_dry_interview",
        "user_id": uid,
        "company": "MegaCorp",
        "status": "interview",
        "interview_at": tomorrow,
        "interview_reminder_sent": False,
        "dry_run": True,
    })

    summary = await application_engine.run_interview_reminder_cycle(uid)
    assert summary["reminders"] == 0
    app = await db.job_applications.find_one({"id": "app_dry_interview"})
    assert app.get("interview_reminder_sent") is False


@pytest.mark.asyncio
async def test_dry_run_ignored_by_board_digest():
    uid = "test_user_dry_isolation"
    await db.job_applications.insert_one({
        "id": "app_dry_board",
        "user_id": uid,
        "channel": "board",
        "status": "awaiting_approval",
        "dry_run": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    count, sent = await application_engine.send_board_digest(uid, {}, None)
    assert count == 0
    assert sent is False
