#!/usr/bin/env python3
"""End-to-End Smoke Test for ApplyPilot (Phase 3 Verification).

Verifies the entire core pipeline:
1. Single-user owner authentication & session cookie.
2. Role profile creation & resume upload/preview.
3. CSV HR contacts import.
4. Bulk application generation & queueing.
5. Dry-run email dispatch & zero-real-send verification.

Usage:
    python scripts/smoke_test.py [--base-url http://localhost:8000]
"""

import argparse
import asyncio
import io
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import bcrypt
import httpx
from pymongo import MongoClient

# Ensure backend directory is in path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "backend"))

# Force test configuration
TEST_DB_NAME = "applypilot_test"
os.environ["DB_NAME"] = TEST_DB_NAME
os.environ["DRY_RUN"] = "true"
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ.setdefault("OWNER_EMAIL", "owner@applypilot.dev")
TEST_PASSWORD = "SecretPassword123"
TEST_HASH = bcrypt.hashpw(TEST_PASSWORD.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")
os.environ.setdefault("OWNER_PASSWORD_HASH", TEST_HASH)
os.environ.setdefault("SESSION_SECRET", "smoke_test_session_secret_32chars_long")
os.environ.setdefault("APP_ENCRYPTION_KEY", "4SloZgHIl31EvC5tYwA-IdT6ZXc6R5JulFBEdZrgRrE=")

from db import db
from server import app


def seed_database_owner():
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    client = MongoClient(mongo_url)
    test_db = client[TEST_DB_NAME]
    # Clean previous run data
    test_db.users.delete_many({"user_id": "owner"})
    test_db.app_settings.delete_many({"user_id": "owner"})
    test_db.role_profiles.delete_many({"user_id": "owner"})
    test_db.resume_versions.delete_many({"user_id": "owner"})
    test_db.hr_contacts.delete_many({"user_id": "owner"})
    test_db.job_opportunities.delete_many({"user_id": "owner"})
    test_db.job_matches.delete_many({"user_id": "owner"})
    test_db.job_applications.delete_many({"user_id": "owner"})
    test_db.bulk_jobs.delete_many({"user_id": "owner"})
    test_db.events.delete_many({"user_id": "owner"})
    test_db.application_events.delete_many({"user_id": "owner"})
    test_db.gmail_connections.delete_many({"user_id": "owner"})

    # Seed owner user & settings
    test_db.users.insert_one({
        "user_id": "owner",
        "email": os.environ["OWNER_EMAIL"],
        "password_hash": os.environ["OWNER_PASSWORD_HASH"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    test_db.gmail_connections.insert_one({
        "user_id": "owner",
        "email": os.environ["OWNER_EMAIL"],
        "status": "connected",
        "access_token": "dummy_access_token",
        "refresh_token": "dummy_refresh_token",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "dummy_client_id",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    test_db.app_settings.insert_one({
        "user_id": "owner",
        "dry_run": True,
        "autopilot": {
            "enabled": True,
            "paused": False,
            "mode": "approval",
            "daily_cap": 25,
            "max_per_day": 25,
            "min_match_score": 70,
            "min_delay_minutes": 15,
        },
        "profile": {
            "full_name": "Test Owner",
            "phone": "+1 555-0199",
            "linkedin": "https://linkedin.com/in/testowner",
            "github": "https://github.com/testowner",
        },
    })
    client.close()


def drop_test_database():
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    client = MongoClient(mongo_url)
    client.drop_database(TEST_DB_NAME)
    client.close()


async def run_smoke_test(base_url: str | None = None):
    print("=" * 65)
    print("           APPLYPILOT END-TO-END SMOKE TEST")
    print("=" * 65)
    print(f"Target DB:     {TEST_DB_NAME}")
    print(f"Dry-Run Mode:  {os.environ.get('DRY_RUN')}")
    print(f"Owner Email:   {os.environ.get('OWNER_EMAIL')}")
    print("-" * 65)

    seed_database_owner()

    # Determine transport: live HTTP server if base_url is specified and responding, else ASGI in-process
    use_live_server = False
    if base_url:
        try:
            async with httpx.AsyncClient(timeout=2.0) as check_client:
                r = await check_client.get(f"{base_url.rstrip('/')}/api/health")
                if r.status_code == 200:
                    use_live_server = True
                    print(f"Server Target: Live server at {base_url}")
        except Exception:
            pass

    if not use_live_server:
        print("Server Target: In-Process FastAPI ASGI Transport")

    # Mock LLM calls if no external API key is present
    has_llm_key = bool(
        os.environ.get("GEMINI_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("ANTHROPIC_API_KEY")
    )
    if not has_llm_key:
        print("LLM Provider:  Simulated Mock (No LLM key configured in environment)")
    else:
        print(f"LLM Provider:  Live ({os.environ.get('LLM_PROVIDER', 'gemini')})")

    async def _execute_steps(client: httpx.AsyncClient):
        # ---------------------------------------------------------------------
        # Step 1: Owner Login & Auth Cookie Verification
        # ---------------------------------------------------------------------
        print("\n[STEP 1] Testing single-user owner login & session cookie...")
        login_resp = await client.post(
            "/api/auth/login",
            json={"email": os.environ["OWNER_EMAIL"], "password": TEST_PASSWORD},
        )
        assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
        assert "applypilot_session" in client.cookies, "Missing applypilot_session cookie in response"
        cookie = client.cookies["applypilot_session"]
        assert len(cookie) > 20, "Session cookie appears malformed"

        me_resp = await client.get("/api/auth/me")
        assert me_resp.status_code == 200, f"/api/auth/me failed: {me_resp.text}"
        me_data = me_resp.json()
        assert me_data.get("ok") is True
        assert me_data.get("user", {}).get("user_id") == "owner"
        assert me_data.get("user", {}).get("email") == os.environ["OWNER_EMAIL"]
        print("  -> Login succeeded. Session cookie set with user_id='owner'. [PASS]")

        # ---------------------------------------------------------------------
        # Step 2: Role Profile Creation & Resume Upload/Preview
        # ---------------------------------------------------------------------
        print("\n[STEP 2] Testing role profile creation & resume upload...")
        role_payload = {
            "title": "Staff Backend Engineer",
            "description": "Architect and scale distributed backend systems with FastAPI and MongoDB.",
            "skills": ["Python", "FastAPI", "MongoDB", "AsyncIO", "Docker"],
            "experience_required": "5+ years",
            "notes": "Primary target profile for technical recruiter outreach.",
        }
        role_resp = await client.post("/api/roles", json=role_payload)
        assert role_resp.status_code == 200, f"Create role failed: {role_resp.text}"
        role_data = role_resp.json()
        role_id = role_data["id"]
        assert role_id, "Missing role_id in response"
        print(f"  -> Role profile '{role_data['title']}' created with ID {role_id}.")

        # Minimal valid PDF file bytes with text content
        pdf_bytes = (
            b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
            b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Contents 4 0 R>>endobj\n"
            b"4 0 obj<</Length 44>>stream\nBT /F1 12 Tf 72 712 Td (Senior Backend Engineer Python FastAPI) Tj ET\nendstream\nendobj\n"
            b"xref\n0 5\n0000000000 65535 f\n0000000009 00000 n\n0000000056 00000 n\n0000000111 00000 n\n0000000202 00000 n\n"
            b"trailer<</Size 5/Root 1 0 R>>\nstartxref\n296\n%%EOF"
        )
        upload_resp = await client.post(
            f"/api/roles/{role_id}/resumes",
            files={"file": ("staff_resume.pdf", pdf_bytes, "application/pdf")},
            data={"name": "Staff Resume v1"},
        )
        assert upload_resp.status_code == 200, f"Upload resume failed: {upload_resp.text}"
        updated_role = upload_resp.json()
        active_resume = updated_role.get("active_resume")
        assert active_resume is not None, f"Expected active_resume in {updated_role}"
        resume_id = active_resume["id"]
        assert active_resume.get("active") is True

        # Verify preview returns file content
        preview_resp = await client.get(f"/api/resumes/{resume_id}/preview")
        assert preview_resp.status_code == 200, f"Resume preview failed: {preview_resp.text}"
        assert len(preview_resp.content) == len(pdf_bytes)
        print(f"  -> Resume uploaded and verified via preview endpoint (ID {resume_id}). [PASS]")

        # ---------------------------------------------------------------------
        # Step 3: CSV Import
        # ---------------------------------------------------------------------
        print("\n[STEP 3] Testing HR contacts CSV import...")
        csv_content = (
            "hr_name,hr_email,company_name,job_role,job_description\n"
            "Sarah Connor,sarah@techcorp.example.com,TechCorp,Staff Backend Engineer,Scale high-volume APIs with Python.\n"
            "John Matrix,john@cloudscale.example.com,CloudScale,Staff Backend Engineer,Build cloud infrastructure using FastAPI.\n"
        )
        import_resp = await client.post(
            "/api/contacts/import",
            files={"file": ("recruiters.csv", csv_content.encode("utf-8"), "text/csv")},
        )
        assert import_resp.status_code == 200, f"CSV import failed: {import_resp.text}"
        import_result = import_resp.json()
        assert import_result["imported"] == 2, f"Expected 2 imported, got {import_result}"
        assert len(import_result["errors"]) == 0

        contacts_resp = await client.get("/api/contacts")
        assert contacts_resp.status_code == 200
        contacts = contacts_resp.json()
        assert len(contacts) == 2
        contact_ids = [c["id"] for c in contacts]
        print(f"  -> Imported {len(contacts)} contacts from CSV successfully. [PASS]")

        # ---------------------------------------------------------------------
        # Step 4: Bulk Application Generation
        # ---------------------------------------------------------------------
        print("\n[STEP 4] Testing bulk application generation...")
        bulk_resp = await client.post(
            "/api/contacts/bulk-generate",
            json={"contact_ids": contact_ids, "queue_for_auto": False},
        )
        assert bulk_resp.status_code == 200, f"Bulk generate request failed: {bulk_resp.text}"
        job_info = bulk_resp.json()
        job_id = job_info["id"]

        # Poll for completion (up to 30s)
        for _ in range(60):
            job_status_resp = await client.get(f"/api/contacts/bulk-jobs/{job_id}")
            assert job_status_resp.status_code == 200
            current_job = job_status_resp.json()
            if current_job.get("status") in ("completed", "failed"):
                break
            await asyncio.sleep(0.5)

        assert current_job.get("status") == "completed", f"Bulk job failed: {current_job}"
        assert current_job.get("done") == 2, f"Expected 2 completed applications, got {current_job}"
        print(f"  -> Bulk generation completed: 2 applications created. [PASS]")

        apps_resp = await client.get("/api/applications")
        assert apps_resp.status_code == 200
        apps_list = apps_resp.json()
        assert len(apps_list) >= 2
        test_app = apps_list[0]
        assert test_app["status"] in ("awaiting_approval", "draft")
        app_id = test_app["id"]

        # ---------------------------------------------------------------------
        # Step 5: Dry-Run Send & Verification
        # ---------------------------------------------------------------------
        print("\n[STEP 5] Testing dry-run send & zero-real-send verification...")
        # Approve application
        approve_resp = await client.post(f"/api/applications/{app_id}/approve")
        assert approve_resp.status_code == 200, f"Approval failed: {approve_resp.text}"

        # Send application in DRY_RUN mode
        send_resp = await client.post(f"/api/applications/{app_id}/send")
        assert send_resp.status_code == 200, f"Send failed: {send_resp.text}"

        # Verify application status and dry_run flag
        app_check_resp = await client.get(f"/api/applications/{app_id}")
        assert app_check_resp.status_code == 200
        app_check = app_check_resp.json()
        assert app_check["status"] == "sent", f"Expected status 'sent', got {app_check.get('status')}"
        assert app_check.get("dry_run") is True, f"Expected dry_run=True, got {app_check.get('dry_run')}"

        # Verify event log records dry_run_send
        events_resp = await client.get(f"/api/tracking/events?application_id={app_id}")
        assert events_resp.status_code == 200
        event_types = [e.get("type") for e in events_resp.json()]
        assert "dry_run_send" in event_types, f"Missing dry_run_send event in {event_types}"
        print("  -> Application marked sent with dry_run=True; dry_run_send event logged.")

        # Test dry-run clear endpoint
        clear_resp = await client.delete("/api/applications/dry-run")
        assert clear_resp.status_code == 200
        clear_data = clear_resp.json()
        assert clear_data.get("ok") is True
        print("  -> Dry-run data purged successfully via DELETE /api/applications/dry-run. [PASS]")

    # If no LLM key is configured, mock the LLM match & generator so the smoke test can run offline
    if not has_llm_key:
        async def mock_match(opp, profiles, model=None):
            return {
                "role_profile_id": profiles[0]["id"] if profiles else "mock_profile",
                "score": 92,
                "confidence": "high",
                "matched_skills": ["Python", "FastAPI"],
                "missing_skills": [],
                "reasoning": "Strong match for backend role.",
            }

        async def mock_gen_email(context: dict, model=None):
            hr = context.get("hr_name") or "Hiring Team"
            title = context.get("job_title") or "Staff Backend Engineer"
            comp = context.get("company_name") or "TechCorp"
            return {
                "subject": f"Staff Backend Engineer Application - Test Owner",
                "body": (
                    f"Hi {hr},\n\n"
                    f"I noticed the {title} role at {comp} and wanted to reach out directly. "
                    "With extensive experience scaling services using Python and FastAPI, "
                    "I am confident I can contribute effectively to your engineering goals."
                ),
            }

        with patch("ai_service.match_opportunity", side_effect=mock_match), \
             patch("ai_service.generate_application_email", side_effect=mock_gen_email):
            if use_live_server:
                async with httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=30.0) as client:
                    await _execute_steps(client)
            else:
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver", timeout=30.0) as client:
                    await _execute_steps(client)
    else:
        if use_live_server:
            async with httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=30.0) as client:
                await _execute_steps(client)
        else:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver", timeout=30.0) as client:
                await _execute_steps(client)

    drop_test_database()
    print("\n" + "=" * 65)
    print("           ALL SMOKE TESTS COMPLETED SUCCESSFULLY!           ")
    print("=" * 65)


def main():
    parser = argparse.ArgumentParser(description="ApplyPilot Smoke Test")
    parser.add_argument("--base-url", default=None, help="Base URL of running ApplyPilot server")
    args = parser.parse_args()

    try:
        asyncio.run(run_smoke_test(args.base_url))
    except Exception as exc:
        print(f"\n[FAIL] Smoke test encountered an error: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        try:
            drop_test_database()
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
