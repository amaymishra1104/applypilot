import asyncio
import os
import sys
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
import pytest_asyncio

from db import db, utc_now_iso
import application_engine
import routes_contacts


@pytest_asyncio.fixture(autouse=True)
async def cleanup_db():
    test_uid = "test_user_varied_openings"
    for col in (
        db.hr_contacts,
        db.job_applications,
        db.job_opportunities,
        db.job_matches,
        db.role_profiles,
        db.resume_versions,
        db.app_settings,
        db.bulk_jobs,
        db.application_events,
    ):
        await col.delete_many({"user_id": test_uid})
    yield test_uid
    for col in (
        db.hr_contacts,
        db.job_applications,
        db.job_opportunities,
        db.job_matches,
        db.role_profiles,
        db.resume_versions,
        db.app_settings,
        db.bulk_jobs,
        db.application_events,
    ):
        await col.delete_many({"user_id": test_uid})


def test_word_limit_applies_before_signature():
    # 1. 179-word body (under 180 word limit)
    words_179 = " ".join(["word"] * 179)
    ok, reason = application_engine.validate_email_draft("Valid Subject", words_179)
    assert ok is True
    assert reason is None

    # 2. Append signature: total words now exceeds 180 (e.g. 182+ words)
    prof_settings = {
        "full_name": "Jane Doe",
        "current_title": "Principal Architect",
        "phone": "+1-555-0199",
        "city_country": "San Francisco, CA",
        "linkedin_url": "https://linkedin.com/in/janedoe",
        "github_url": "https://github.com/janedoe",
    }
    full_body_with_sig = application_engine.append_signature(words_179, prof_settings)
    total_words = len(full_body_with_sig.split())
    assert total_words > 180, "Full body including signature exceeds 180 words"

    # 3. If raw generated body itself exceeds 180 words, validation fails
    words_185 = " ".join(["word"] * 185)
    ok_fail, reason_fail = application_engine.validate_email_draft("Valid Subject", words_185)
    assert ok_fail is False
    assert "exceeds 180 words" in reason_fail


@pytest.mark.asyncio
async def test_bulk_generation_varied_openings_and_style_hints():
    uid = "test_user_varied_openings"

    # Set up profile and resume
    profile = {
        "id": "prof_openings_test",
        "user_id": uid,
        "title": "Backend Systems Engineer",
        "title_norm": "backend systems engineer",
        "skills": ["Distributed Systems", "Go", "Python"],
        "active_resume_version_id": "res_openings_test",
        "created_at": utc_now_iso(),
    }
    await db.role_profiles.insert_one(profile)

    resume = {
        "id": "res_openings_test",
        "user_id": uid,
        "role_profile_id": "prof_openings_test",
        "name": "systems_resume.pdf",
        "storage_path": "resumes/systems.pdf",
        "filename": "systems.pdf",
        "active": True,
        "is_deleted": False,
        "resume_text": "Staff Backend Engineer specialized in high-throughput distributed systems.",
        "created_at": utc_now_iso(),
    }
    await db.resume_versions.insert_one(resume)

    await db.app_settings.insert_one({
        "user_id": uid,
        "profile": {"full_name": "Alex Tech"},
        "autopilot": {"mode": "approval", "max_per_day": 50},
    })

    # Create 6 contacts
    contacts = []
    for i in range(1, 7):
        contacts.append({
            "id": f"contact_open_{i}",
            "user_id": uid,
            "company_name": f"Company {i}",
            "hr_name": f"Recruiter {i}",
            "hr_email": f"recruiter{i}@company{i}.com",
            "hr_email_norm": f"recruiter{i}@company{i}.com",
            "job_role": "Backend Systems Engineer",
            "created_at": utc_now_iso(),
        })
    await db.hr_contacts.insert_many(contacts)

    captured_contexts = []
    mock_lock = asyncio.Lock()

    async def mock_generate_email(ctx, model=None):
        async with mock_lock:
            captured_contexts.append(dict(ctx))
            idx = len(captured_contexts)
        # Return an email with a distinct opening line
        opening_line = f"I have followed Company {idx}'s work in distributed databases with great admiration."
        return {
            "subject": f"Backend Systems Engineer - Company {idx}",
            "body": f"Dear Recruiter {idx},\n\n{opening_line}\n\nI would love to contribute.\n\nBest regards,",
        }

    mock_match = {"role_profile_id": "prof_openings_test", "score": 88, "matched_skills": ["Go"]}

    job_id = "job_varied_openings_test"
    job_doc = {
        "id": job_id,
        "user_id": uid,
        "status": "pending",
        "total": 6,
        "done": 0,
        "failed": 0,
        "skipped": 0,
        "contact_ids": [c["id"] for c in contacts],
        "processed_ids": [],
        "errors": [],
        "created_at": utc_now_iso(),
        "updated_at": utc_now_iso(),
    }
    await db.bulk_jobs.insert_one(job_doc)

    with patch("ai_service.match_opportunity", AsyncMock(return_value=mock_match)), \
         patch("ai_service.generate_application_email", side_effect=mock_generate_email):
        await routes_contacts.run_bulk_generation_job(job_id, uid)

    job = await db.bulk_jobs.find_one({"id": job_id})
    assert job["status"] == "completed"
    assert job["done"] == 6
    assert len(captured_contexts) == 6

    # Verify rotating style hints were passed to generator contexts
    style_hints_seen = [ctx.get("style_hint") for ctx in captured_contexts]
    assert all(h is not None for h in style_hints_seen)
    # The 6th hint should wrap around to the first hint
    assert style_hints_seen[0] == style_hints_seen[5]
    # Check at least 3 distinct style hints used across the 6 contacts
    assert len(set(style_hints_seen)) >= 3

    # Verify recent openings were accumulated and passed to later contacts
    # The first contact had no previous openings in this batch
    assert captured_contexts[0].get("recent_openings") == []

    # Later contacts received openings from earlier completed contacts
    last_context = captured_contexts[-1]
    # Since concurrency is 3, by contact 5 or 6, earlier contacts have completed and populated recent_openings
    has_recent = any(len(ctx.get("recent_openings", [])) > 0 for ctx in captured_contexts[1:])
    assert has_recent is True, "Later contexts should have received recent_openings from earlier contacts in the batch"

    # Verify all 6 applications were created
    apps = await db.job_applications.find({"user_id": uid}).to_list(10)
    assert len(apps) == 6
