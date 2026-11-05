import asyncio
import os
import sys
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
import pytest_asyncio

from db import db, utc_now_iso
import routes_contacts
import server


@pytest_asyncio.fixture(autouse=True)
async def cleanup_db():
    test_uid = "test_user_bulk_resume"
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


@pytest.mark.asyncio
async def test_resume_running_bulk_jobs_on_startup():
    uid = "test_user_bulk_resume"

    # Set up role profile and active resume
    profile = {
        "id": "prof_resume_test",
        "user_id": uid,
        "title": "Fullstack Engineer",
        "title_norm": "fullstack engineer",
        "skills": ["Python", "React", "MongoDB"],
        "active_resume_version_id": "res_resume_test",
        "created_at": utc_now_iso(),
    }
    await db.role_profiles.insert_one(profile)

    resume = {
        "id": "res_resume_test",
        "user_id": uid,
        "role_profile_id": "prof_resume_test",
        "name": "fullstack_resume.pdf",
        "storage_path": "resumes/fullstack.pdf",
        "filename": "fullstack.pdf",
        "active": True,
        "is_deleted": False,
        "resume_text": "Experienced Fullstack Engineer with Python and React.",
        "created_at": utc_now_iso(),
    }
    await db.resume_versions.insert_one(resume)

    await db.app_settings.insert_one({
        "user_id": uid,
        "profile": {"full_name": "Dev User"},
        "autopilot": {"mode": "approval", "max_per_day": 20},
    })

    # Create 3 contacts
    c1 = {
        "id": "contact_res_1",
        "user_id": uid,
        "company_name": "Alpha Corp",
        "hr_name": "Alice",
        "hr_email": "alice@alphacorp.com",
        "hr_email_norm": "alice@alphacorp.com",
        "job_role": "Fullstack Engineer",
        "created_at": utc_now_iso(),
    }
    c2 = {
        "id": "contact_res_2",
        "user_id": uid,
        "company_name": "Beta Corp",
        "hr_name": "Bob",
        "hr_email": "bob@betacorp.com",
        "hr_email_norm": "bob@betacorp.com",
        "job_role": "Fullstack Engineer",
        "created_at": utc_now_iso(),
    }
    c3 = {
        "id": "contact_res_3",
        "user_id": uid,
        "company_name": "Gamma Corp",
        "hr_name": "Charlie",
        "hr_email": "charlie@gammacorp.com",
        "hr_email_norm": "charlie@gammacorp.com",
        "job_role": "Fullstack Engineer",
        "created_at": utc_now_iso(),
    }
    await db.hr_contacts.insert_many([c1, c2, c3])

    # Simulate C1 was already processed before server crash
    app_c1 = {
        "id": "app_existing_c1",
        "user_id": uid,
        "company": "Alpha Corp",
        "job_title": "Fullstack Engineer",
        "job_title_norm": "fullstack engineer",
        "hr_email": "alice@alphacorp.com",
        "status": "awaiting_approval",
        "created_at": utc_now_iso(),
    }
    await db.job_applications.insert_one(app_c1)

    # Insert an interrupted running job doc
    job_id = "bulk_job_interrupted"
    job_doc = {
        "id": job_id,
        "user_id": uid,
        "status": "running",
        "total": 3,
        "done": 1,
        "failed": 0,
        "skipped": 0,
        "contact_ids": [c1["id"], c2["id"], c3["id"]],
        "processed_ids": [c1["id"]],
        "errors": [],
        "created_at": utc_now_iso(),
        "updated_at": utc_now_iso(),
    }
    await db.bulk_jobs.insert_one(job_doc)

    mock_match = {"role_profile_id": "prof_resume_test", "score": 85, "matched_skills": ["Python"]}
    mock_email = {
        "subject": "Application for Fullstack Engineer",
        "body": "Hello, I am excited to apply for the Fullstack Engineer position.",
    }

    with patch("ai_service.match_opportunity", AsyncMock(return_value=mock_match)), \
         patch("ai_service.generate_application_email", AsyncMock(return_value=mock_email)):
        resumed_ids = await server.resume_running_bulk_jobs()
        assert job_id in resumed_ids

        # Wait for the background task to complete
        for _ in range(50):
            job = await db.bulk_jobs.find_one({"id": job_id})
            if job and job.get("status") == "completed":
                break
            await asyncio.sleep(0.1)

    job = await db.bulk_jobs.find_one({"id": job_id})
    assert job["status"] == "completed"
    assert job["done"] == 3
    assert job["failed"] == 0
    assert job["skipped"] == 0

    # Verify applications in DB: exactly 3 applications, C1 was NOT duplicated
    apps = await db.job_applications.find({"user_id": uid}).to_list(10)
    assert len(apps) == 3

    emails = [a["hr_email"] for a in apps]
    assert sorted(emails) == ["alice@alphacorp.com", "bob@betacorp.com", "charlie@gammacorp.com"]

    # Verify running resume_running_bulk_jobs again finds no running jobs
    resumed_again = await server.resume_running_bulk_jobs()
    assert resumed_again == []
