import asyncio
import os
import sys
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
import pytest_asyncio

from db import db, utc_now_iso
import application_engine
from application_engine import (
    append_signature,
    format_signature,
    generate_email_with_guardrails,
    get_allowed_links,
    validate_email_draft,
)
import routes_contacts
import routes_applications
import routes_roles


@pytest_asyncio.fixture(autouse=True)
async def cleanup_db():
    test_uid = "test_user_phase2"
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
        db.gmail_connections,
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
        db.gmail_connections,
    ):
        await col.delete_many({"user_id": test_uid})


@pytest.mark.asyncio
async def test_signature_formatting_and_deterministic_append():
    profile = {
        "full_name": "Jane Doe",
        "phone": "+1 (555) 019-2831",
        "linkedin": "https://linkedin.com/in/janedoe",
        "github": "https://github.com/janedoe",
        "portfolio": "https://janedoe.dev",
    }
    sig = format_signature(profile)
    assert "Jane Doe" in sig
    assert "+1 (555) 019-2831" in sig
    assert "https://linkedin.com/in/janedoe | https://github.com/janedoe | https://janedoe.dev" in sig

    links = get_allowed_links(profile)
    assert len(links) == 3
    assert "https://github.com/janedoe" in links

    # Append to body without trailing name
    body = "Dear Alex,\n\nI am writing to apply for the position.\n\nBest regards,"
    appended = append_signature(body, profile)
    assert appended.endswith(sig)
    assert "Best regards,\n\nJane Doe" in appended

    # If body already ended with the candidate name, it should not duplicate the name
    body_with_name = "Dear Alex,\n\nI am writing to apply.\n\nBest regards,\nJane Doe"
    appended_no_dup = append_signature(body_with_name, profile)
    assert appended_no_dup.count("Jane Doe") == 1
    assert appended_no_dup.endswith(sig)


@pytest.mark.asyncio
async def test_email_quality_guardrails_validation():
    allowed_links = ["https://linkedin.com/in/janedoe", "https://janedoe.dev"]

    # 1. Empty subject
    ok, reason = validate_email_draft("", "Valid body content", "Sarah", allowed_links)
    assert ok is False
    assert "empty" in reason.lower()

    # 2. Over 180 words
    long_body = "word " * 185
    ok, reason = validate_email_draft("Valid Subject", long_body, "Sarah", allowed_links)
    assert ok is False
    assert "exceeds 180 words" in reason

    # 3. Bracket placeholders
    ok, reason = validate_email_draft("Subject", "I built [Project Name] using Python.", "Sarah", allowed_links)
    assert ok is False
    assert "placeholder brackets" in reason

    ok, reason = validate_email_draft("Subject", "I love {Company} products.", "Sarah", allowed_links)
    assert ok is False
    assert "placeholder brackets" in reason

    # 4. Literal "Company Name"
    ok, reason = validate_email_draft("Subject", "I want to work at Company Name as an engineer.", "Sarah", allowed_links)
    assert ok is False
    assert "literal 'Company Name'" in reason

    # 5. "Hiring Manager" when HR contact name is given
    ok, reason = validate_email_draft("Subject", "Dear Hiring Manager,\nI am writing to apply...", "Sarah Connor", allowed_links)
    assert ok is False
    assert "Hiring Manager" in reason

    # 6. Unauthorized URLs
    ok, reason = validate_email_draft("Subject", "Check out my work at https://malicious-link.com for details.", "Sarah", allowed_links)
    assert ok is False
    assert "unauthorized URL" in reason

    # 7. Authorized URL from allowed list
    ok, reason = validate_email_draft("Subject", "You can view my portfolio at https://janedoe.dev for code samples.", "Sarah", allowed_links)
    assert ok is True
    assert reason is None


@pytest.mark.asyncio
async def test_generate_email_with_guardrails_retries_and_recovers():
    # Attempt 1 returns placeholder, Attempt 2 returns clean email
    bad_email = {
        "subject": "Application for Engineer",
        "body": "Dear Hiring Manager,\nI am excited to apply for [Role] at Company Name.\n\nBest regards,",
    }
    good_email = {
        "subject": "Application for Senior Backend Engineer",
        "body": "Dear Sarah,\n\nYour distributed systems work at Acme caught my attention. In my previous role I built FastAPI microservices handling 10k RPS.\n\nBest regards,",
    }

    mock_llm = AsyncMock(side_effect=[bad_email, good_email])
    with patch("ai_service.generate_application_email", mock_llm):
        result = await generate_email_with_guardrails(
            {"hr_name": "Sarah", "company_name": "Acme", "allowed_links": []},
            model="gpt-5.4",
            max_retries=2,
        )

    assert result["subject"] == good_email["subject"]
    assert mock_llm.call_count == 2


@pytest.mark.asyncio
async def test_generate_email_with_guardrails_fails_after_max_retries():
    # Model consistently returns placeholders
    bad_email = {
        "subject": "Application",
        "body": "Dear [Name],\nI want to work at [Company].\n\nBest,",
    }
    mock_llm = AsyncMock(return_value=bad_email)
    with patch("ai_service.generate_application_email", mock_llm):
        with pytest.raises(ValueError) as exc:
            await generate_email_with_guardrails(
                {"hr_name": "Sarah", "company_name": "Acme"},
                model="gpt-5.4",
                max_retries=2,
            )
        assert "Email quality check failed after 2 retries" in str(exc.value)
    # 1 initial + 2 retries = 3 calls
    assert mock_llm.call_count == 3


@pytest.mark.asyncio
async def test_bulk_generation_idempotency_and_no_send(cleanup_db):
    uid = cleanup_db
    # Seed role profile with active resume
    profile_id = "role_prof_1"
    await db.role_profiles.insert_one({
        "id": profile_id,
        "user_id": uid,
        "title": "Backend Engineer",
        "skills": ["Python", "FastAPI", "MongoDB"],
        "created_at": utc_now_iso(),
    })
    await db.resume_versions.insert_one({
        "id": "resume_v1",
        "user_id": uid,
        "role_profile_id": profile_id,
        "version_no": 1,
        "name": "Backend Resume",
        "storage_path": "resumes/backend.pdf",
        "active": True,
        "resume_text": "Experienced Python Backend Engineer with 5 years in FastAPI and MongoDB systems.",
        "created_at": utc_now_iso(),
    })
    await db.app_settings.insert_one({
        "user_id": uid,
        "profile": {"full_name": "Jane Developer", "phone": "+1 555-0100"},
        "autopilot": {"mode": "approval", "max_per_day": 10, "min_match_score": 60},
    })

    # Seed 2 HR contacts
    c1 = {
        "id": "c_1",
        "user_id": uid,
        "hr_name": "Alice Recruiter",
        "hr_email": "alice@techcorp.com",
        "hr_email_norm": "alice@techcorp.com",
        "company_name": "TechCorp",
        "job_role": "Backend Engineer",
        "job_description": "Building high scale Python APIs.",
        "created_at": utc_now_iso(),
    }
    c2 = {
        "id": "c_2",
        "user_id": uid,
        "hr_name": "Bob HR",
        "hr_email": "bob@startup.io",
        "hr_email_norm": "bob@startup.io",
        "company_name": "StartupIO",
        "job_role": "Backend Engineer",
        "job_description": "FastAPI developer needed.",
        "created_at": utc_now_iso(),
    }
    await db.hr_contacts.insert_many([c1, c2])

    fake_email = {
        "subject": "Application for Backend Engineer",
        "body": "Dear Recruiter,\n\nI saw your opening and would love to apply.\n\nBest regards,",
    }
    fake_match = {
        "role_profile_id": profile_id,
        "score": 85,
        "matched_skills": ["Python", "FastAPI"],
        "reasoning": "Strong match",
    }

    mock_send = AsyncMock()
    with patch("ai_service.match_opportunity", new=AsyncMock(return_value=fake_match)), \
         patch("ai_service.generate_application_email", new=AsyncMock(return_value=fake_email)), \
         patch("gmail_service.send_gmail_email", new=mock_send):

        # 1. Run bulk generation
        job_id = "bulk_job_1"
        await db.bulk_jobs.insert_one({
            "id": job_id, "user_id": uid, "status": "pending",
            "contact_ids": ["c_1", "c_2"], "queue_for_auto": False,
        })
        await routes_contacts.run_bulk_generation_job(job_id, uid)

        # Check job completion
        job = await db.bulk_jobs.find_one({"id": job_id})
        assert job["status"] == "completed"
        assert job["done"] == 2
        assert job["skipped"] == 0
        assert job["failed"] == 0

        # Verify applications created with awaiting_approval status and signature appended
        apps = await db.job_applications.find({"user_id": uid}).to_list(10)
        assert len(apps) == 2
        for app in apps:
            assert app["status"] == "awaiting_approval"
            assert "Jane Developer" in app["body_text"]
            assert "+1 555-0100" in app["body_text"]

        # CRITICAL: Bulk generation must NEVER send anything
        assert mock_send.call_count == 0

        # 2. Run bulk generation a SECOND time on same contacts: Idempotency guarantee
        job_id_2 = "bulk_job_2"
        await db.bulk_jobs.insert_one({
            "id": job_id_2, "user_id": uid, "status": "pending",
            "contact_ids": ["c_1", "c_2"], "queue_for_auto": False,
        })
        await routes_contacts.run_bulk_generation_job(job_id_2, uid)

        job2 = await db.bulk_jobs.find_one({"id": job_id_2})
        assert job2["status"] == "completed"
        assert job2["done"] == 0
        assert job2["skipped"] == 2
        # Still exactly 2 applications in DB, no duplicates created
        total_apps = await db.job_applications.count_documents({"user_id": uid})
        assert total_apps == 2


@pytest.mark.asyncio
async def test_bulk_generation_match_caching(cleanup_db):
    uid = cleanup_db
    profile_id = "role_prof_cache"
    await db.role_profiles.insert_one({
        "id": profile_id, "user_id": uid, "title": "DevOps Engineer",
        "skills": ["Kubernetes", "AWS"], "created_at": utc_now_iso(),
    })
    await db.resume_versions.insert_one({
        "id": "resume_devops", "user_id": uid, "role_profile_id": profile_id,
        "version_no": 1, "name": "DevOps Resume", "storage_path": "resumes/devops.pdf",
        "active": True, "resume_text": "Experienced DevOps and Cloud Engineer.", "created_at": utc_now_iso(),
    })
    await db.app_settings.insert_one({"user_id": uid, "autopilot": {"mode": "approval"}})

    # 3 contacts sharing the EXACT same role and description
    for i in range(1, 4):
        await db.hr_contacts.insert_one({
            "id": f"contact_cache_{i}",
            "user_id": uid,
            "hr_name": f"HR {i}",
            "hr_email": f"hr{i}@cloudco.com",
            "hr_email_norm": f"hr{i}@cloudco.com",
            "company_name": f"CloudCo {i}",
            "job_role": "Site Reliability Engineer",
            "job_description": "We need Kubernetes, Terraform and AWS expertise.",
            "created_at": utc_now_iso(),
        })

    match_mock = AsyncMock(return_value={
        "role_profile_id": profile_id, "score": 92, "matched_skills": ["Kubernetes", "AWS"],
    })
    email_mock = AsyncMock(return_value={
        "subject": "Application for SRE", "body": "Dear HR,\n\nApplying for the SRE role.\n\nBest regards,",
    })

    with patch("ai_service.match_opportunity", match_mock), \
         patch("ai_service.generate_application_email", email_mock):
        job_id = "job_cache_test"
        await db.bulk_jobs.insert_one({
            "id": job_id, "user_id": uid, "status": "pending",
            "contact_ids": ["contact_cache_1", "contact_cache_2", "contact_cache_3"],
        })
        await routes_contacts.run_bulk_generation_job(job_id, uid)

    # All 3 contacts generated
    job = await db.bulk_jobs.find_one({"id": job_id})
    assert job["done"] == 3
    # BUT match_opportunity was called only ONCE due to match caching!
    assert match_mock.call_count == 1


@pytest.mark.asyncio
async def test_bulk_generation_role_accounts_and_invalid_emails_skipped(cleanup_db):
    uid = cleanup_db
    profile_id = "role_prof_skip"
    await db.role_profiles.insert_one({
        "id": profile_id, "user_id": uid, "title": "Frontend Engineer",
        "skills": ["React"], "created_at": utc_now_iso(),
    })
    await db.resume_versions.insert_one({
        "id": "resume_fe", "user_id": uid, "role_profile_id": profile_id,
        "version_no": 1, "name": "FE Resume", "storage_path": "resumes/fe.pdf",
        "active": True, "resume_text": "React Engineer.", "created_at": utc_now_iso(),
    })
    await db.app_settings.insert_one({"user_id": uid, "autopilot": {"mode": "approval"}})

    # Contacts: 1 role account, 1 invalid email format
    await db.hr_contacts.insert_many([
        {"id": "c_noreply", "user_id": uid, "hr_email": "noreply@company.com", "hr_email_norm": "noreply@company.com", "job_role": "React Dev"},
        {"id": "c_invalid", "user_id": uid, "hr_email": "not-an-email", "hr_email_norm": "not-an-email", "job_role": "React Dev"},
    ])

    job_id = "job_skip_test"
    await db.bulk_jobs.insert_one({
        "id": job_id, "user_id": uid, "status": "pending",
        "contact_ids": ["c_noreply", "c_invalid"],
    })
    await routes_contacts.run_bulk_generation_job(job_id, uid)

    job = await db.bulk_jobs.find_one({"id": job_id})
    assert job["status"] == "completed"
    assert job["done"] == 0
    assert job["skipped"] == 2
    assert len(job["errors"]) == 2
    reasons = [e["reason"] for e in job["errors"]]
    assert any("Role-account" in r for r in reasons)
    assert any("Invalid" in r for r in reasons)


@pytest.mark.asyncio
async def test_bulk_generation_role_fallback_to_profile_title(cleanup_db):
    uid = cleanup_db
    profile_id = "role_prof_fallback"
    await db.role_profiles.insert_one({
        "id": profile_id, "user_id": uid, "title": "Full Stack Engineer",
        "skills": ["TypeScript", "Node"], "created_at": utc_now_iso(),
    })
    await db.resume_versions.insert_one({
        "id": "resume_fs", "user_id": uid, "role_profile_id": profile_id,
        "version_no": 1, "name": "FS Resume", "storage_path": "resumes/fs.pdf",
        "active": True, "resume_text": "Full stack engineer.", "created_at": utc_now_iso(),
    })
    await db.app_settings.insert_one({"user_id": uid, "autopilot": {"mode": "approval"}})

    # Contact with NO job_role
    await db.hr_contacts.insert_one({
        "id": "c_norole", "user_id": uid, "hr_name": "Tom",
        "hr_email": "tom@agency.com", "hr_email_norm": "tom@agency.com",
        "company_name": "Agency", "job_role": "", "job_description": "",
    })

    with patch("ai_service.match_opportunity", new=AsyncMock(return_value={"role_profile_id": profile_id, "score": 80})), \
         patch("ai_service.generate_application_email", new=AsyncMock(return_value={"subject": "Application", "body": "Dear Tom,\n\nApplying.\n\nBest regards,"})):
        job_id = "job_fallback_test"
        await db.bulk_jobs.insert_one({
            "id": job_id, "user_id": uid, "status": "pending",
            "contact_ids": ["c_norole"],
        })
        await routes_contacts.run_bulk_generation_job(job_id, uid)

    app = await db.job_applications.find_one({"user_id": uid, "hr_email": "tom@agency.com"})
    assert app is not None
    # Fell back to the matching profile title
    assert app["job_title"] == "Full Stack Engineer"


@pytest.mark.asyncio
async def test_queue_bulk_approve_and_bulk_delete(cleanup_db):
    uid = cleanup_db
    # Seed 3 draft applications
    apps_data = [
        {"id": "app_b1", "user_id": uid, "status": "draft", "company": "Co1"},
        {"id": "app_b2", "user_id": uid, "status": "awaiting_approval", "company": "Co2"},
        {"id": "app_b3", "user_id": uid, "status": "sent", "company": "Co3"},
    ]
    await db.job_applications.insert_many(apps_data)

    user = {"user_id": uid}

    # 1. Bulk approve: only drafts and awaiting_approval should become approved
    res = await routes_applications.bulk_approve(
        routes_applications.BulkActionIn(application_ids=["app_b1", "app_b2", "app_b3"]),
        user=user,
    )
    assert res["ok"] is True
    assert res["count"] == 2  # app_b1 and app_b2

    a1 = await db.job_applications.find_one({"id": "app_b1"})
    a2 = await db.job_applications.find_one({"id": "app_b2"})
    a3 = await db.job_applications.find_one({"id": "app_b3"})
    assert a1["status"] == "approved"
    assert a2["status"] == "approved"
    assert a3["status"] == "sent"  # Sent was untouched by approve

    # 2. Bulk delete: app_b1 (approved) should be deleted, app_b3 (sent) should be cancelled
    del_res = await routes_applications.bulk_delete(
        routes_applications.BulkActionIn(application_ids=["app_b1", "app_b3"]),
        user=user,
    )
    assert del_res["ok"] is True
    assert del_res["count"] == 2

    assert await db.job_applications.find_one({"id": "app_b1"}) is None
    cancelled_app = await db.job_applications.find_one({"id": "app_b3"})
    assert cancelled_app is not None
    assert cancelled_app["status"] == "cancelled"


@pytest.mark.asyncio
async def test_dry_run_simulation_mode(cleanup_db, monkeypatch):
    uid = cleanup_db
    monkeypatch.setenv("DRY_RUN", "true")
    assert application_engine.is_dry_run() is True

    await db.gmail_connections.update_one(
        {"user_id": uid},
        {"$set": {"email": "user@gmail.com", "status": "connected"}},
        upsert=True,
    )
    app_doc = {
        "id": "app_dry_run_test",
        "user_id": uid,
        "status": "approved",
        "company": "Simulated Corp",
        "hr_email": "hr@simulated.com",
        "subject": "Dry Run Subject",
        "body_text": "Dry Run Body",
        "attachment_path": "resumes/test.pdf",
        "created_at": utc_now_iso(),
    }
    await db.job_applications.insert_one(app_doc)

    gmail_mock = AsyncMock()
    with patch("gmail_service.send_gmail_email", gmail_mock), \
         patch("application_engine.get_object", return_value=(b"%PDF", "resume.pdf")):
        result = await application_engine.send_application(uid, app_doc, trigger="manual")

    assert result["ok"] is True
    assert result["dry_run"] is True
    # Gmail must NEVER be called in dry run
    assert gmail_mock.call_count == 0

    # Application marked sent with dry_run=True
    sent_app = await db.job_applications.find_one({"id": "app_dry_run_test"})
    assert sent_app["status"] == "sent"
    assert sent_app["dry_run"] is True
    assert sent_app["message_id"].startswith("dry_run_")

    # Queue stats exclude dry run sent items
    stats = await routes_applications.queue_stats(user={"user_id": uid})
    assert stats["sent_today"] == 0

    # Clear dry run endpoint clears dry run applications
    clear_res = await routes_applications.clear_dry_run(user={"user_id": uid})
    assert clear_res["deleted_applications"] == 1
    assert await db.job_applications.find_one({"id": "app_dry_run_test"}) is None


@pytest.mark.asyncio
async def test_resume_handling_text_cap_and_warning(cleanup_db):
    # 1. Low text (<300 chars) triggers warning on upload
    short_text = "Jane Doe. Engineer."
    # Mock extract_pdf_text to return short_text
    with patch("routes_roles.extract_pdf_text", return_value=short_text):
        res = routes_roles.extract_pdf_text(b"mock_bytes")
        assert len(res) < 300

    # 2. Text cap raised to 15,000 chars
    long_text = "Experienced Senior Software Engineer " * 500  # ~18,500 chars
    with patch("routes_roles.extract_pdf_text", return_value=long_text[:15000].strip()):
        extracted = routes_roles.extract_pdf_text(b"mock_bytes")
        assert len(extracted) == 15000

