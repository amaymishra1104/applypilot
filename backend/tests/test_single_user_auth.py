import os
import sys
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from server import app
from db import db, utc_now_iso
import auth
from auth import (
    COOKIE_NAME,
    OWNER_USER_ID,
    create_session_token,
    validate_owner_config,
    _failed_attempts,
    _login_lock,
)


@pytest.fixture(autouse=True)
def reset_auth_state():
    _failed_attempts.clear()
    yield
    _failed_attempts.clear()


@pytest.mark.asyncio
async def test_owner_login_success_sets_httponly_cookie():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Correct owner credentials
        res = await client.post(
            "/api/auth/login",
            json={"email": "owner@applypilot.dev", "password": "SecretPassword123"},
        )
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        data = res.json()
        assert data["ok"] is True
        assert data["user"]["user_id"] == OWNER_USER_ID
        assert data["user"]["email"] == "owner@applypilot.dev"

        # Verify HttpOnly session cookie
        assert COOKIE_NAME in res.cookies
        cookie_header = res.headers.get("set-cookie", "")
        assert "HttpOnly" in cookie_header
        assert "SameSite=lax" in cookie_header or "samesite=lax" in cookie_header.lower()

        # Follow up with GET /api/auth/me using the client's session cookie
        me_res = await client.get("/api/auth/me")
        assert me_res.status_code == 200
        assert me_res.json()["user"]["user_id"] == OWNER_USER_ID

        # Test logout clears the cookie
        logout_res = await client.post("/api/auth/logout")
        assert logout_res.status_code == 200

        # After logout, me_res returns 401
        me_after_res = await client.get("/api/auth/me")
        assert me_after_res.status_code == 401


@pytest.mark.asyncio
async def test_owner_login_wrong_credentials():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Wrong password
        res = await client.post(
            "/api/auth/login",
            json={"email": "owner@applypilot.dev", "password": "WrongPassword!"},
        )
        assert res.status_code == 401
        assert "Invalid email or password" in res.json()["detail"]

        # Wrong email
        res2 = await client.post(
            "/api/auth/login",
            json={"email": "intruder@domain.com", "password": "SecretPassword123"},
        )
        assert res2.status_code == 401
        assert "Invalid email or password" in res2.json()["detail"]


@pytest.mark.asyncio
async def test_login_rate_limiting_lockout():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for _ in range(5):
            r = await client.post(
                "/api/auth/login",
                json={"email": "owner@applypilot.dev", "password": "WrongPassword!"},
            )
            assert r.status_code == 401

        # 6th attempt triggers 429 lockout
        locked = await client.post(
            "/api/auth/login",
            json={"email": "owner@applypilot.dev", "password": "SecretPassword123"},
        )
        assert locked.status_code == 429
        assert "Too many failed login attempts" in locked.json()["detail"]


@pytest.mark.asyncio
async def test_resume_preview_and_download_with_cookie():
    uid = OWNER_USER_ID
    version_id = "res_test_preview_cookie"
    await db.resume_versions.delete_many({"user_id": uid})
    await db.resume_versions.insert_one({
        "id": version_id,
        "user_id": uid,
        "role_profile_id": "prof_test",
        "name": "resume.pdf",
        "storage_path": "resumes/resume.pdf",
        "filename": "my_resume.pdf",
        "active": True,
        "is_deleted": False,
        "created_at": utc_now_iso(),
    })

    token = create_session_token("owner@applypilot.dev")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Without cookie -> 401
        res_no_auth = await client.get(f"/api/resumes/{version_id}/preview")
        assert res_no_auth.status_code == 401

        # 2. With cookie -> 200
        client.cookies.set(COOKIE_NAME, token)
        with patch("routes_roles.get_object", return_value=(b"%PDF-1.5 test resume", "my_resume.pdf")):
            res_preview = await client.get(f"/api/resumes/{version_id}/preview")
            assert res_preview.status_code == 200
            assert res_preview.headers["content-type"] == "application/pdf"
            assert "inline" in res_preview.headers["content-disposition"]

            res_download = await client.get(f"/api/resumes/{version_id}/download")
            assert res_download.status_code == 200
            assert "attachment" in res_download.headers["content-disposition"]


@pytest.mark.asyncio
async def test_extension_token_auth_stays_as_is():
    import secrets
    import hashlib
    raw_token = "apx_" + secrets.token_urlsafe(32)
    tok_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    await db.extension_tokens.delete_many({"user_id": OWNER_USER_ID})
    await db.extension_tokens.insert_one({
        "user_id": OWNER_USER_ID,
        "token_hash": tok_hash,
        "created_at": utc_now_iso(),
        "revoked": False,
    })

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Without any header or cookie -> 401
        res_no_auth = await client.get("/api/ext/me")
        assert res_no_auth.status_code == 401

        # With X-ApplyPilot-Token header -> 200
        res = await client.get("/api/ext/me", headers={"X-ApplyPilot-Token": raw_token})
        assert res.status_code == 200
        data = res.json()
        assert "email" in data


def test_startup_fails_without_owner_env(monkeypatch):
    monkeypatch.delenv("OWNER_EMAIL", raising=False)
    with pytest.raises(RuntimeError) as exc_info:
        validate_owner_config()
    assert "OWNER_EMAIL" in str(exc_info.value)
