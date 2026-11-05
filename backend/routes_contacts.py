import asyncio
import csv
import hashlib
import io
import logging
import re
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

import ai_service
from application_engine import (add_event, append_signature, count_sent_today,
                                duplicate_application_exists, email_is_valid,
                                generate_email_with_guardrails, get_allowed_links,
                                get_profiles_with_resumes, get_settings, normalize)
from db import db, utc_now_iso
from deps import get_current_user, get_owned

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["contacts"])

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

ROLE_ACCOUNT_PREFIXES = (
    "noreply@", "no-reply@", "donotreply@", "do-not-reply@",
    "mailer-daemon@", "postmaster@"
)


def is_role_account(email: str) -> bool:
    email_lower = (email or "").strip().lower()
    return any(email_lower.startswith(p) for p in ROLE_ACCOUNT_PREFIXES)


FIELDS = ["company_name", "hr_name", "hr_email", "company_website", "job_role",
          "job_description", "application_source", "notes", "last_contacted_at"]

HEADER_ALIASES = {
    "company": "company_name", "company_name": "company_name", "companyname": "company_name",
    "hr_name": "hr_name", "name": "hr_name", "recruiter_name": "hr_name", "hrname": "hr_name",
    "hr_email": "hr_email", "email": "hr_email", "email_address": "hr_email", "hremail": "hr_email",
    "company_website": "company_website", "website": "company_website", "url": "company_website",
    "job_role": "job_role", "role": "job_role", "position": "job_role",
    "job_description": "job_description", "description": "job_description",
    "application_source": "application_source", "source": "application_source",
    "notes": "notes", "note": "notes",
}


class ContactIn(BaseModel):
    company_name: str = ""
    hr_name: str = ""
    hr_email: str
    company_website: str = ""
    job_role: str = ""
    job_description: str = ""
    application_source: str = ""
    notes: str = ""


def norm_email(email: str) -> str:
    return (email or "").strip().lower()


async def find_duplicate(user_id: str, email: str) -> Optional[dict]:
    return await db.hr_contacts.find_one(
        {"user_id": user_id, "hr_email_norm": norm_email(email)}, {"_id": 0})


def build_doc(user_id: str, data: dict) -> dict:
    doc = {"id": uuid.uuid4().hex, "user_id": user_id}
    for field in FIELDS:
        value = data.get(field) or ""
        doc[field] = str(value).strip()[:4000]
    doc["hr_email"] = norm_email(doc["hr_email"])
    doc["hr_email_norm"] = doc["hr_email"]
    doc["created_at"] = utc_now_iso()
    return doc


@router.get("/contacts")
async def list_contacts(search: str = "", user: dict = Depends(get_current_user)):
    query = {"user_id": user["user_id"]}
    if search.strip():
        rx = {"$regex": re.escape(search.strip()), "$options": "i"}
        query["$or"] = [{"company_name": rx}, {"hr_name": rx}, {"hr_email": rx}, {"job_role": rx}]
    contacts = await db.hr_contacts.find(query, {"_id": 0}).sort("created_at", -1).to_list(1000)

    apps = await db.job_applications.find(
        {"user_id": user["user_id"]},
        {"_id": 0, "id": 1, "hr_email": 1, "status": 1, "sent_at": 1, "created_at": 1, "bounced": 1, "reply_received": 1}
    ).to_list(5000)

    apps_by_email = {}
    for a in apps:
        email = norm_email(a.get("hr_email", ""))
        if email:
            existing = apps_by_email.get(email)
            if not existing or (a.get("created_at") or "") > (existing.get("created_at") or ""):
                apps_by_email[email] = a

    for c in contacts:
        app = apps_by_email.get(c.get("hr_email_norm", norm_email(c.get("hr_email", ""))))
        if not app:
            c["application_status"] = "no_application"
        else:
            raw_st = app.get("status", "")
            if app.get("bounced") or raw_st == "bounced":
                c["application_status"] = "bounced"
            elif app.get("reply_received") or raw_st in ("replied", "interview"):
                c["application_status"] = "replied"
            elif raw_st in ("sent", "followup_due"):
                c["application_status"] = "sent"
            elif raw_st == "approved":
                c["application_status"] = "approved"
            else:
                c["application_status"] = "draft"
            if not c.get("last_contacted_at") and app.get("sent_at"):
                c["last_contacted_at"] = app["sent_at"]
    return contacts


class BulkGenerateIn(BaseModel):
    contact_ids: Optional[list[str]] = None
    select_all_without_app: bool = False
    queue_for_auto: bool = False


async def run_bulk_generation_job(job_id: str, user_id: str):
    job = await db.bulk_jobs.find_one({"id": job_id, "user_id": user_id})
    if not job or job.get("status") in ("completed", "failed"):
        return

    await db.bulk_jobs.update_one(
        {"id": job_id},
        {"$set": {"status": "running", "updated_at": utc_now_iso()}}
    )

    profiles = await get_profiles_with_resumes(user_id)
    if not profiles:
        await db.bulk_jobs.update_one(
            {"id": job_id},
            {"$set": {
                "status": "failed",
                "errors": [{"contact_id": "", "email": "", "reason": "No role profiles found. Please create a role profile and upload an active resume first."}],
                "updated_at": utc_now_iso(),
                "completed_at": utc_now_iso(),
            }}
        )
        return

    settings = await get_settings(user_id)
    prof_settings = settings.get("profile") or {}
    allowed_links = get_allowed_links(prof_settings)
    candidate_name = prof_settings.get("full_name") or "Candidate"
    queue_for_auto = bool(job.get("queue_for_auto"))
    daily_limit = settings.get("autopilot", {}).get("max_per_day", 10)
    min_match_score = settings.get("autopilot", {}).get("min_match_score", 60)
    mode = settings.get("autopilot", {}).get("mode", "approval")

    contact_ids = job.get("contact_ids") or []
    contacts = await db.hr_contacts.find({"user_id": user_id, "id": {"$in": contact_ids}}, {"_id": 0}).to_list(len(contact_ids))
    contact_map = {c["id"]: c for c in contacts}
    target_contacts = [contact_map[cid] for cid in contact_ids if cid in contact_map]

    match_cache = {}
    sem = asyncio.Semaphore(3)
    lock = asyncio.Lock()

    done = int(job.get("done", 0))
    failed = int(job.get("failed", 0))
    skipped = int(job.get("skipped", 0))
    errors = list(job.get("errors", []))

    async def process_contact(contact: dict):
        nonlocal done, failed, skipped
        email = norm_email(contact.get("hr_email", ""))

        if not email or not email_is_valid(email):
            async with lock:
                skipped += 1
                errors.append({"contact_id": contact["id"], "email": email, "reason": "Invalid or disposable email address"})
                await db.bulk_jobs.update_one(
                    {"id": job_id},
                    {"$set": {"done": done, "failed": failed, "skipped": skipped, "errors": errors, "updated_at": utc_now_iso()}}
                )
            return

        if is_role_account(email):
            async with lock:
                skipped += 1
                errors.append({"contact_id": contact["id"], "email": email, "reason": f"Role-account address ({email}) skipped"})
                await db.bulk_jobs.update_one(
                    {"id": job_id},
                    {"$set": {"done": done, "failed": failed, "skipped": skipped, "errors": errors, "updated_at": utc_now_iso()}}
                )
            return

        target_role = (contact.get("job_role") or "").strip()
        job_desc = (contact.get("job_description") or "").strip()
        company_name = (contact.get("company_name") or "").strip() or "Company"

        if target_role and await duplicate_application_exists(user_id, email, target_role):
            async with lock:
                skipped += 1
                errors.append({"contact_id": contact["id"], "email": email, "reason": f"Application already exists for role '{target_role}'"})
                await db.bulk_jobs.update_one(
                    {"id": job_id},
                    {"$set": {"done": done, "failed": failed, "skipped": skipped, "errors": errors, "updated_at": utc_now_iso()}}
                )
            return

        cache_key = f"{normalize(target_role)}:{hashlib.sha256(job_desc.encode()).hexdigest()[:16]}"
        match_result = None
        async with lock:
            if cache_key in match_cache:
                match_result = match_cache[cache_key]

        if not match_result:
            opp_payload = {
                "company_name": company_name,
                "job_title": target_role or profiles[0]["title"],
                "required_skills": [],
                "experience_required": "",
                "description_summary": job_desc[:1500] if job_desc else None,
                "job_description": job_desc,
            }
            for _ in range(2):
                try:
                    match_result = await ai_service.match_opportunity(opp_payload, profiles, settings.get("ai_model"))
                    if match_result and match_result.get("role_profile_id"):
                        break
                except Exception as exc:
                    logger.warning(f"Bulk match error: {exc}")
                    await asyncio.sleep(0.5)

            if not match_result or not match_result.get("role_profile_id"):
                match_result = {
                    "role_profile_id": profiles[0]["id"],
                    "score": 60,
                    "matched_skills": profiles[0].get("skills", []),
                    "reasoning": "Selected best matching profile",
                }
            async with lock:
                match_cache[cache_key] = match_result

        matched_profile = next((p for p in profiles if p["id"] == match_result["role_profile_id"]), profiles[0])
        active_resume = matched_profile.get("active_resume")
        if not active_resume:
            active_resume = await db.resume_versions.find_one(
                {"user_id": user_id, "role_profile_id": matched_profile["id"], "is_deleted": {"$ne": True}, "active": True},
                {"_id": 0}
            )

        if not active_resume:
            async with lock:
                failed += 1
                errors.append({"contact_id": contact["id"], "email": email, "reason": f"No active resume for role profile '{matched_profile['title']}'"})
                await db.bulk_jobs.update_one(
                    {"id": job_id},
                    {"$set": {"done": done, "failed": failed, "skipped": skipped, "errors": errors, "updated_at": utc_now_iso()}}
                )
            return

        final_role_title = target_role or matched_profile["title"]

        if not target_role and await duplicate_application_exists(user_id, email, final_role_title):
            async with lock:
                skipped += 1
                errors.append({"contact_id": contact["id"], "email": email, "reason": f"Application already exists for role '{final_role_title}'"})
                await db.bulk_jobs.update_one(
                    {"id": job_id},
                    {"$set": {"done": done, "failed": failed, "skipped": skipped, "errors": errors, "updated_at": utc_now_iso()}}
                )
            return

        opp = await db.job_opportunities.find_one({"user_id": user_id, "hr_contact_id": contact["id"]}, {"_id": 0})
        if not opp:
            opp = {
                "id": uuid.uuid4().hex,
                "user_id": user_id,
                "company_name": company_name,
                "job_title": final_role_title,
                "job_title_norm": normalize(final_role_title),
                "job_description": job_desc,
                "required_skills": match_result.get("matched_skills", []),
                "experience_required": matched_profile.get("experience_required", ""),
                "source": "bulk_generator",
                "hr_contact_id": contact["id"],
                "status": "matched",
                "created_at": utc_now_iso(),
            }
            await db.job_opportunities.insert_one(opp.copy())

        match_doc = {
            "id": uuid.uuid4().hex,
            "user_id": user_id,
            "opportunity_id": opp["id"],
            "role_profile_id": matched_profile["id"],
            "role_profile_title": matched_profile["title"],
            "resume_version_id": active_resume["id"],
            "resume_version_no": active_resume.get("version_no", 1),
            "resume_name": active_resume.get("name", "resume"),
            "score": int(match_result.get("score", 60)),
            "confidence": match_result.get("confidence", "medium"),
            "matched_skills": match_result.get("matched_skills", []),
            "missing_skills": match_result.get("missing_skills", []),
            "reasoning": match_result.get("reasoning", ""),
            "confirmed": False,
            "created_at": utc_now_iso(),
        }
        await db.job_matches.delete_many({"user_id": user_id, "opportunity_id": opp["id"]})
        await db.job_matches.insert_one(match_doc.copy())

        gen_context = {
            "hr_name": contact.get("hr_name", ""),
            "hr_email": email,
            "company_name": company_name,
            "job_title": final_role_title,
            "required_skills": match_result.get("matched_skills", []) or opp.get("required_skills", []),
            "description_summary": job_desc[:1500] if job_desc else None,
            "company_background": "",
            "role_title": matched_profile["title"],
            "role_skills": matched_profile.get("skills", []),
            "experience_required": matched_profile.get("experience_required", ""),
            "role_notes": matched_profile.get("notes", ""),
            "matched_skills": match_result.get("matched_skills", []),
            "resume_text": active_resume.get("resume_text", ""),
            "tone": settings.get("email_tone", "professional"),
            "candidate_name": candidate_name,
            "allowed_links": allowed_links,
        }

        try:
            generated = await generate_email_with_guardrails(gen_context, settings.get("ai_model"))
        except Exception as exc:
            async with lock:
                failed += 1
                errors.append({"contact_id": contact["id"], "email": email, "reason": f"Email generation failed: {exc}"})
                await db.bulk_jobs.update_one(
                    {"id": job_id},
                    {"$set": {"done": done, "failed": failed, "skipped": skipped, "errors": errors, "updated_at": utc_now_iso()}}
                )
            return

        body_text = append_signature(generated.get("body", ""), prof_settings)
        score = int(match_result.get("score", 60))

        if queue_for_auto:
            sent_today = await count_sent_today(user_id)
            queued_count = await db.job_applications.count_documents({"user_id": user_id, "status": "queued_auto"})
            if mode == "auto" and score >= min_match_score and (sent_today + queued_count) < daily_limit:
                status = "queued_auto"
                match_doc["confirmed"] = True
                await db.job_matches.update_one({"id": match_doc["id"]}, {"$set": {"confirmed": True}})
            else:
                status = "awaiting_approval"
        else:
            status = "draft" if mode == "manual" else "awaiting_approval"

        app_doc = {
            "id": uuid.uuid4().hex,
            "user_id": user_id,
            "opportunity_id": opp["id"],
            "match_id": match_doc["id"],
            "company": company_name,
            "job_title": final_role_title,
            "job_title_norm": normalize(final_role_title),
            "hr_name": contact.get("hr_name", ""),
            "hr_email": email,
            "role_profile_id": matched_profile["id"],
            "role_profile_title": matched_profile["title"],
            "resume_version_id": active_resume["id"],
            "resume_version_no": active_resume.get("version_no", 1),
            "resume_name": active_resume.get("name", "resume"),
            "attachment_path": active_resume["storage_path"],
            "attachment_filename": active_resume.get("filename") or "resume.pdf",
            "attachment_size": active_resume.get("size", 0),
            "match_score": score,
            "subject": generated.get("subject", f"Application for {final_role_title}"),
            "body_text": body_text,
            "status": status,
            "retries": 0,
            "sent_at": None,
            "message_id": None,
            "latest_response": "",
            "next_followup_at": None,
            "error": None,
            "created_at": utc_now_iso(),
        }
        await db.job_applications.insert_one(app_doc.copy())
        await add_event(user_id, app_doc["id"], "bulk_application_generated", f"Bulk generated application for {final_role_title} at {company_name}")

        async with lock:
            done += 1
            await db.bulk_jobs.update_one(
                {"id": job_id},
                {"$set": {"done": done, "failed": failed, "skipped": skipped, "errors": errors, "updated_at": utc_now_iso()}}
            )

    async def worker(c):
        async with sem:
            await process_contact(c)

    await asyncio.gather(*(worker(c) for c in target_contacts))

    await db.bulk_jobs.update_one(
        {"id": job_id},
        {"$set": {
            "status": "completed",
            "done": done,
            "failed": failed,
            "skipped": skipped,
            "errors": errors,
            "updated_at": utc_now_iso(),
            "completed_at": utc_now_iso(),
        }}
    )


@router.post("/contacts/bulk-generate")
async def bulk_generate(body: BulkGenerateIn, user: dict = Depends(get_current_user)):
    user_id = user["user_id"]
    contact_ids = body.contact_ids or []
    if body.select_all_without_app or not contact_ids:
        all_contacts = await db.hr_contacts.find({"user_id": user_id}, {"_id": 0, "id": 1, "hr_email_norm": 1}).to_list(2000)
        apps = await db.job_applications.find({"user_id": user_id, "status": {"$ne": "cancelled"}}, {"_id": 0, "hr_email": 1}).to_list(5000)
        app_emails = {norm_email(a.get("hr_email", "")) for a in apps}
        target_ids = [c["id"] for c in all_contacts if c.get("hr_email_norm") not in app_emails]
    else:
        target_ids = contact_ids

    if not target_ids:
        raise HTTPException(status_code=400, detail="No eligible contacts found for application generation")

    job_id = uuid.uuid4().hex
    job_doc = {
        "id": job_id,
        "user_id": user_id,
        "status": "pending",
        "total": len(target_ids),
        "done": 0,
        "failed": 0,
        "skipped": 0,
        "errors": [],
        "contact_ids": target_ids,
        "queue_for_auto": bool(body.queue_for_auto),
        "created_at": utc_now_iso(),
        "updated_at": utc_now_iso(),
        "completed_at": None,
    }
    await db.bulk_jobs.insert_one(job_doc.copy())
    asyncio.create_task(run_bulk_generation_job(job_id, user_id))
    return job_doc


@router.get("/contacts/bulk-jobs/active")
async def get_active_bulk_job(user: dict = Depends(get_current_user)):
    job = await db.bulk_jobs.find_one(
        {"user_id": user["user_id"], "status": {"$in": ["pending", "running"]}},
        {"_id": 0},
        sort=[("created_at", -1)]
    )
    return {"job": job}


@router.get("/contacts/bulk-jobs/{job_id}")
async def get_bulk_job(job_id: str, user: dict = Depends(get_current_user)):
    job = await db.bulk_jobs.find_one({"id": job_id, "user_id": user["user_id"]}, {"_id": 0})
    if not job:
        raise HTTPException(status_code=404, detail="Bulk job not found")
    return job


def _normalize_headers(rows: list[dict]) -> list[dict]:
    mapped = []
    for row in rows:
        item = {}
        for key, value in row.items():
            clean = re.sub(r"[\s\-]+", "_", str(key or "").strip().lower())
            field = HEADER_ALIASES.get(clean) or (clean if clean in FIELDS else None)
            if field:
                item[field] = value
        mapped.append(item)
    return mapped


def _read_spreadsheet(filename: str, data: bytes) -> list[dict]:
    name = (filename or "").lower()
    if name.endswith(".xlsx") or name.endswith(".xls"):
        try:
            from openpyxl import load_workbook

            wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            ws = wb.active
            rows = list(ws.iter_rows(values_only=True))
            if not rows:
                return []
            headers = [str(h) if h is not None else "" for h in rows[0]]
            return [dict(zip(headers, r)) for r in rows[1:] if any(v is not None for v in r)]
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Could not read Excel file: {exc}")
    try:
        text = data.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        return list(reader)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not read CSV file: {exc}")


@router.post("/contacts/import")
async def import_contacts(file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    data = await file.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 5 MB)")
    rows = _normalize_headers(_read_spreadsheet(file.filename, data))
    result = {"imported": 0, "duplicates": [], "errors": []}
    seen_in_file = set()
    for index, row in enumerate(rows, start=2):
        email = norm_email(str(row.get("hr_email") or ""))
        if not email:
            result["errors"].append({"row": index, "reason": "Missing HR email"})
            continue
        if not EMAIL_RE.match(email):
            result["errors"].append({"row": index, "reason": f"Invalid email: {email}"})
            continue
        if email in seen_in_file:
            result["duplicates"].append({"row": index, "reason": f"Duplicate in file: {email}"})
            continue
        if await find_duplicate(user["user_id"], email):
            result["duplicates"].append({"row": index, "reason": f"Already exists: {email}"})
            continue
        seen_in_file.add(email)
        await db.hr_contacts.insert_one(build_doc(user["user_id"], row).copy())
        result["imported"] += 1
    return result


@router.post("/contacts")
async def create_contact(body: ContactIn, user: dict = Depends(get_current_user)):
    if not EMAIL_RE.match(norm_email(body.hr_email)):
        raise HTTPException(status_code=400, detail="Invalid email address")
    if await find_duplicate(user["user_id"], body.hr_email):
        raise HTTPException(status_code=409, detail="A contact with this email already exists")
    doc = build_doc(user["user_id"], body.model_dump())
    await db.hr_contacts.insert_one(doc.copy())
    return doc


@router.put("/contacts/{contact_id}")
async def update_contact(contact_id: str, body: ContactIn, user: dict = Depends(get_current_user)):
    await get_owned("hr_contacts", contact_id, user["user_id"])
    if not EMAIL_RE.match(norm_email(body.hr_email)):
        raise HTTPException(status_code=400, detail="Invalid email address")
    dup = await find_duplicate(user["user_id"], body.hr_email)
    if dup and dup["id"] != contact_id:
        raise HTTPException(status_code=409, detail="A contact with this email already exists")
    doc = build_doc(user["user_id"], body.model_dump())
    doc["id"] = contact_id
    await db.hr_contacts.replace_one({"id": contact_id, "user_id": user["user_id"]}, doc)
    return doc


@router.delete("/contacts/{contact_id}")
async def delete_contact(contact_id: str, user: dict = Depends(get_current_user)):
    await get_owned("hr_contacts", contact_id, user["user_id"])
    await db.hr_contacts.delete_one({"id": contact_id, "user_id": user["user_id"]})
    return {"ok": True}
