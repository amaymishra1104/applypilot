import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

sys.path.insert(0, str(Path(__file__).parent.parent))

from db import db
from mailer import notify_user, send_email


@pytest.mark.asyncio
async def test_notification_via_connected_gmail():
    uid = "test_gmail_owner"
    await db.gmail_connections.update_one(
        {"user_id": uid},
        {"$set": {"status": "connected", "email": "owner@gmail.com"}},
        upsert=True,
    )

    mock_send = AsyncMock(return_value=("gmail_msg_12345", "th_12345"))
    with patch("gmail_service.send_gmail_email", mock_send):
        res = await send_email(
            to="owner@gmail.com",
            subject="Interview scheduled",
            html="<p>Your interview is set for tomorrow.</p>",
            user_id=uid,
        )

        assert res == "gmail_gmail_msg_12345"
        mock_send.assert_called_once()
        args, kwargs = mock_send.call_args
        assert kwargs["to"] == "owner@gmail.com"
        assert kwargs["subject"] == "Interview scheduled"
        assert "interview is set" in kwargs["body_text"]
        assert "<p>Your interview is set" in kwargs["html_body"]


@pytest.mark.asyncio
async def test_notification_fallback_to_smtp(monkeypatch):
    uid = "test_smtp_owner"
    # Ensure no connected Gmail
    await db.gmail_connections.delete_many({"user_id": uid})

    monkeypatch.setenv("SMTP_HOST", "smtp.testmail.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "notifications@testmail.com")
    monkeypatch.setenv("SMTP_PASSWORD", "secret_pass")

    with patch("mailer._send_smtp_sync", return_value="smtp_mocked_id_789") as mock_smtp:
        res = await send_email(
            to="owner@applypilot.dev",
            subject="HR Reply Received",
            html="<p>Acme Corp replied to your application.</p>",
            user_id=uid,
        )

        assert res == "smtp_mocked_id_789"
        mock_smtp.assert_called_once()
        args, kwargs = mock_smtp.call_args
        assert kwargs["to"] == "owner@applypilot.dev"
        assert kwargs["subject"] == "HR Reply Received"


@pytest.mark.asyncio
async def test_notification_fallback_to_log_only(monkeypatch, caplog):
    uid = "test_log_owner"
    # Ensure no connected Gmail and no SMTP
    await db.gmail_connections.delete_many({"user_id": uid})
    monkeypatch.delenv("SMTP_HOST", raising=False)

    import logging
    with caplog.at_level(logging.WARNING):
        res = await notify_user(
            {"user_id": uid, "email": "owner@applypilot.dev"},
            "application_sent",
            {"company": "Stripe", "role": "Backend Engineer", "resume": "v1"},
        )

        assert res is not None
        assert res.startswith("log_only_")
        assert "neither connected Gmail nor SMTP is available" in caplog.text
        assert "Stripe" in caplog.text


@pytest.mark.asyncio
async def test_unsafe_email_raises_error():
    with pytest.raises(ValueError) as exc:
        await send_email(
            to="victim@example.com",
            subject="Phishing",
            html="<form action='http://steal.com'><input type='password'></form>",
        )
    assert "No forms or input fields" in str(exc.value)
