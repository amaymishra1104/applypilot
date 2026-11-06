import asyncio
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

import ai_service
from application_engine import (add_event, append_signature, count_sent_today,
                                duplicate_application_exists, email_is_valid,
                                generate_email_with_guardrails, get_allowed_links,
                                get_settings, normalize, send_application)
from db import db, utc_now_iso, parse_iso
from deps import get_current_user, get_owned
from storage import get_object

router = APIRouter(prefix="/api", tags=["applications"])


class GenerateIn(BaseModel):
    opportunity_id: str
    role_profile_id: Optional[str] = None
    resume_version_id: Optional[str] = None
    notes: str = ""


class ApplicationEdit(BaseModel):
    subject: Optional[str] = None
    body_text: Optional[str] = None


class BulkActionIn(BaseModel):
    application_ids: list[str]


class AutopilotIn(BaseModel):
    enabled: Optional[bool] = None
    mode: Optional[str] = None
    max_per_day: Optional[int] = None
    min_delay_minutes: Optional[int] = None
    max_retries: Optional[int] = None
    min_match_score: Optional[int] = None
    paused: Optional[bool] = None


class StatusIn(BaseModel):
    status: str


class InterviewIn(BaseModel):
    interview_at: str
    notes: str = ""


STATUS_VALUES = {"draft", "awaiting_approval", "queued_auto", "scheduled", "approved", "sending", "sent",
                 "send_failed", "replied", "interview", "rejected", "offer", "cancelled",
                 "needs_attention", "submitting"}


async def _resolve_match(user_id: str, opportunity_id: str) -> Optional[dict]:
    return await db.job_matches.find_one({"user_id": user_id, "opportunity_id": opportunity_id}, {"_id": 0})


@router.post("/applications/generate")
async def generate_application(body: GenerateIn, user: dict = Depends(get_current_user)):
    uid = user["user_id"]
    opp = await get_owned("job_opportunities", body.opportunity_id, uid)
    match = await _resolve_match(uid, body.opportunity_id)
    if not match:
        raise HTTPException(status_code=400, detail="Run the AI match for this opportunity first")

    role_profile_id = body.role_profile_id or match["role_profile_id"]
    profile = await get_owned("role_profiles", role_profile_id, uid)
    if body.role_profile_id and body.role_profile_id != match["role_profile_id"]:
        match = {**match, "role_profile_id": profile["id"], "role_profile_title": profile["title"],
                 "overridden": True, "confirmed": True}
        await db.job_matches.update_one({"id": match["id"]}, {"$set": {
            "role_profile_id": profile["id"], "role_profile_title": profile["title"],
            "overridden": True, "confirmed": True}})

    resume_version_id = body.resume_version_id or match.get("resume_version_id")
    if not resume_version_id:
        raise HTTPException(status_code=400, detail="The selected role profile has no active resume - upload one first")
    version = await db.resume_versions.find_one(
        {"id": resume_version_id, "user_id": uid, "is_deleted": {"$ne": True}}, {"_id": 0})
    if not version:
        raise HTTPException(status_code=404, detail="Resume version not found")

    hr_contact = None
    if opp.get("hr_contact_id"):
        hr_contact = await db.hr_contacts.find_one({"id": opp["hr_contact_id"], "user_id": uid}, {"_id": 0})
    if not hr_contact:
        hr_contact = await db.hr_contacts.find_one(
            {"user_id": uid, "company_name": opp.get("company_name", "")}, {"_id": 0}) if opp.get("company_name") else None

    company_name = opp.get("company_name") or (hr_contact or {}).get("company_name", "")
    hr_email = (hr_contact or {}).get("hr_email", "")
    if not hr_email:
        raise HTTPException(status_code=400, detail="No HR email found for this opportunity - assign an HR contact first")
    if not email_is_valid(hr_email):
        raise HTTPException(status_code=400, detail=f"Invalid HR email address: {hr_email}")
    if await duplicate_application_exists(uid, hr_email, opp.get("job_title", "")):
        raise HTTPException(status_code=409, detail="An application to this HR contact for this position already exists")

    settings = await get_settings(uid)
    company_doc = await db.companies.find_one({"user_id": uid, "name": company_name.strip()}, {"_id": 0}) if company_name else None
    prof_settings = settings.get("profile") or {}
    allowed_links = get_allowed_links(prof_settings)
    candidate_name = prof_settings.get("full_name") or user.get("name", "")

    context = {
        "hr_name": (hr_contact or {}).get("hr_name", ""),
        "hr_email": hr_email,
        "company_name": company_name,
        "job_title": opp.get("job_title", ""),
        "required_skills": opp.get("required_skills", []) or match.get("matched_skills", []),
        "description_summary": opp.get("job_description", "")[:1500],
        "company_background": (company_doc or {}).get("background", ""),
        "role_title": profile["title"],
        "role_skills": profile.get("skills", []),
        "experience_required": profile.get("experience_required", ""),
        "role_notes": (body.notes or profile.get("notes", "")),
        "matched_skills": match.get("matched_skills", []),
        "resume_text": version.get("resume_text", ""),
        "tone": settings.get("email_tone", "professional"),
        "candidate_name": candidate_name,
        "allowed_links": allowed_links,
    }
    try:
        email = await generate_email_with_guardrails(context, settings.get("ai_model"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"AI could not generate the email: {exc}")

    body_text = append_signature(email.get("body", ""), prof_settings)

    mode = settings.get("autopilot", {}).get("mode", "approval")
    autop = settings.get("autopilot", {})
    score = int(match.get("score", 0))
    min_score = int(autop.get("min_match_score", 60))
    if mode == "auto" and score >= min_score:
        match["confirmed"] = True
        await db.job_matches.update_one({"id": match["id"]}, {"$set": {"confirmed": True}})
        status = "queued_auto"
    elif mode == "manual":
        status = "draft"
    else:
        status = "awaiting_approval"

    app_doc = {
        "id": uuid.uuid4().hex,
        "user_id": uid,
        "opportunity_id": opp["id"],
        "match_id": match["id"],
        "company": company_name,
        "job_title": opp.get("job_title", ""),
        "job_title_norm": normalize(opp.get("job_title", "")),
        "hr_name": (hr_contact or {}).get("hr_name", ""),
        "hr_email": normalize(hr_email),
        "role_profile_id": profile["id"],
        "role_profile_title": profile["title"],
        "resume_version_id": version["id"],
        "resume_version_no": version["version_no"],
        "resume_name": version["name"],
        "attachment_path": version["storage_path"],
        "attachment_filename": version.get("filename") or "resume.pdf",
        "attachment_size": version.get("size", 0),
        "match_score": score,
        "subject": email.get("subject", f"Application for {opp.get('job_title', '')}"),
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
    await add_event(uid, app_doc["id"], "draft_created",
                    f"Draft created for {company_name} using {profile['title']} resume v{version['version_no']}",
                    {"match_score": score, "status": status})
    app_doc.pop("_id", None)
    return app_doc


@router.get("/applications")
async def list_applications(status: str = "", search: str = "", include_dry_run: bool = False,
                            user: dict = Depends(get_current_user)):
    query = {"user_id": user["user_id"]}
    if not include_dry_run:
        query["dry_run"] = {"$ne": True}
    if status:
        query["status"] = status
    if search.strip():
        rx = {"$regex": re.escape(search.strip()), "$options": "i"}
        query["$or"] = [{"company": rx}, {"job_title": rx}, {"hr_email": rx}]
    docs = await db.job_applications.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)
    return docs


@router.get("/applications/queue-stats")
async def queue_stats(user: dict = Depends(get_current_user)):
    uid = user["user_id"]
    counts = {}
    for status in STATUS_VALUES:
        counts[status] = await db.job_applications.count_documents({
            "user_id": uid, "status": status, "dry_run": {"$ne": True}
        })
    settings = await get_settings(uid)
    return {"counts": counts, "sent_today": await count_sent_today(uid),
            "autopilot": settings.get("autopilot", {}), "gmail_connected": bool(
                await db.gmail_connections.find_one({"user_id": uid, "status": "connected"}, {"_id": 0}))}


@router.delete("/applications/dry-run")
async def clear_dry_run(user: dict = Depends(get_current_user)):
    uid = user["user_id"]
    dry_apps = await db.job_applications.find({"user_id": uid, "dry_run": True}, {"id": 1}).to_list(1000)
    app_ids = [a["id"] for a in dry_apps]
    res_apps = await db.job_applications.delete_many({"user_id": uid, "dry_run": True})
    res_events = await db.application_events.delete_many(
        {"user_id": uid, "$or": [{"type": "dry_run_send"}, {"application_id": {"$in": app_ids}}]}
    )
    return {"ok": True, "deleted_applications": res_apps.deleted_count, "deleted_events": res_events.deleted_count}


@router.post("/applications/bulk-approve")
async def bulk_approve(body: BulkActionIn, user: dict = Depends(get_current_user)):
    uid = user["user_id"]
    ids = body.application_ids or []
    if not ids:
        return {"ok": True, "count": 0}
    result = await db.job_applications.update_many(
        {"user_id": uid, "id": {"$in": ids}, "status": {"$in": ["draft", "awaiting_approval"]}},
        {"$set": {"status": "approved", "updated_at": utc_now_iso()}}
    )
    for app_id in ids:
        await add_event(uid, app_id, "approved", "Email approved in bulk")
    return {"ok": True, "count": result.modified_count}


@router.post("/applications/bulk-delete")
async def bulk_delete(body: BulkActionIn, user: dict = Depends(get_current_user)):
    uid = user["user_id"]
    ids = body.application_ids or []
    if not ids:
        return {"ok": True, "count": 0}
    delete_res = await db.job_applications.delete_many(
        {"user_id": uid, "id": {"$in": ids}, "status": {"$ne": "sent"}}
    )
    cancel_res = await db.job_applications.update_many(
        {"user_id": uid, "id": {"$in": ids}, "status": "sent"},
        {"$set": {"status": "cancelled", "updated_at": utc_now_iso()}}
    )
    total = cancel_res.modified_count + delete_res.deleted_count
    return {"ok": True, "count": total}


@router.get("/applications/{app_id}")
async def get_application(app_id: str, user: dict = Depends(get_current_user)):
    return await get_owned("job_applications", app_id, user["user_id"])


@router.put("/applications/{app_id}")
async def edit_application(app_id: str, body: ApplicationEdit, user: dict = Depends(get_current_user)):
    app_doc = await get_owned("job_applications", app_id, user["user_id"])
    if app_doc.get("status") == "sent":
        raise HTTPException(status_code=400, detail="Sent applications cannot be edited")
    updates = {}
    if body.subject is not None:
        updates["subject"] = body.subject.strip()[:300]
    if body.body_text is not None:
        updates["body_text"] = body.body_text[:20000]
    if updates:
        await db.job_applications.update_one({"id": app_id, "user_id": user["user_id"]}, {"$set": updates})
    return await db.job_applications.find_one({"id": app_id, "user_id": user["user_id"]}, {"_id": 0})


_send_rate_lock = asyncio.Lock()
_send_timestamps: list[float] = []
MAX_MANUAL_SENDS_PER_MINUTE = 15


async def check_send_rate_limit() -> None:
    now = time.time()
    async with _send_rate_lock:
        global _send_timestamps
        _send_timestamps = [t for t in _send_timestamps if now - t < 60]
        if len(_send_timestamps) >= MAX_MANUAL_SENDS_PER_MINUTE:
            raise HTTPException(status_code=429, detail="Too many send requests. Please wait a moment.")
        _send_timestamps.append(now)


@router.post("/applications/{app_id}/send")
async def send_now(app_id: str, force_send: bool = False, user: dict = Depends(get_current_user)):
    await check_send_rate_limit()
    uid = user["user_id"]
    app_doc = await get_owned("job_applications", app_id, uid)
    if app_doc.get("status") == "sent":
        raise HTTPException(status_code=400, detail="Application was already sent")
    if app_doc.get("status") == "sending":
        raise HTTPException(status_code=409, detail="Application is already being sent")
    settings = await get_settings(uid)
    sent_today = await count_sent_today(uid)
    if sent_today >= int(settings["autopilot"]["max_per_day"]):
        raise HTTPException(status_code=429, detail=f"Daily sending limit reached ({settings['autopilot']['max_per_day']}/day). Raise it in Settings.")
    if force_send:
        app_doc["force_send"] = True
    result = await send_application(uid, app_doc, trigger="manual")
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return {"ok": True}


@router.post("/applications/{app_id}/approve")
async def approve_application(app_id: str, user: dict = Depends(get_current_user)):
    app_doc = await get_owned("job_applications", app_id, user["user_id"])
    if app_doc.get("status") not in ("awaiting_approval", "draft"):
        raise HTTPException(status_code=400, detail="Only drafts can be approved")
    await db.job_applications.update_one({"id": app_id, "user_id": user["user_id"]},
                                         {"$set": {"status": "approved"}})
    await add_event(user["user_id"], app_id, "approved", "Email approved by user")
    return {"ok": True}


@router.post("/applications/{app_id}/retry")
async def retry_application(app_id: str, user: dict = Depends(get_current_user)):
    app_doc = await get_owned("job_applications", app_id, user["user_id"])
    if app_doc.get("status") not in ("send_failed", "needs_attention"):
        raise HTTPException(status_code=400, detail="Only failed applications can be retried")
    await db.job_applications.update_one({"id": app_id, "user_id": user["user_id"]},
                                         {"$set": {"status": "approved", "error": None}})
    return {"ok": True}


@router.post("/applications/{app_id}/status")
async def set_status(app_id: str, body: StatusIn, user: dict = Depends(get_current_user)):
    await get_owned("job_applications", app_id, user["user_id"])
    if body.status not in STATUS_VALUES:
        raise HTTPException(status_code=400, detail="Unknown status")
    await db.job_applications.update_one({"id": app_id, "user_id": user["user_id"]},
                                         {"$set": {"status": body.status}})
    await add_event(user["user_id"], app_id, "status_changed", f"Status set to {body.status}")
    return {"ok": True}


@router.post("/applications/{app_id}/schedule-interview")
async def schedule_interview(app_id: str, body: InterviewIn, user: dict = Depends(get_current_user)):
    await get_owned("job_applications", app_id, user["user_id"])
    when = parse_iso(body.interview_at)
    if not when:
        raise HTTPException(status_code=400, detail="Invalid interview date/time")
    if when < datetime.now(timezone.utc) - timedelta(minutes=5):
        raise HTTPException(status_code=400, detail="Interview time is in the past")
    await db.job_applications.update_one(
        {"id": app_id, "user_id": user["user_id"]},
        {"$set": {"status": "interview", "interview_at": when.isoformat(),
                  "interview_notes": body.notes.strip()[:2000],
                  "interview_reminder_sent": False, "next_followup_at": None}})
    await add_event(user["user_id"], app_id, "interview_scheduled",
                    f"Interview scheduled for {when.strftime('%d %b %Y %H:%M UTC')}")
    return {"ok": True, "interview_at": when.isoformat()}


@router.delete("/applications/{app_id}")
async def delete_application(app_id: str, user: dict = Depends(get_current_user)):
    app_doc = await get_owned("job_applications", app_id, user["user_id"])
    if app_doc.get("status") == "sent":
        await db.job_applications.update_one({"id": app_id, "user_id": user["user_id"]},
                                             {"$set": {"status": "cancelled"}})
        return {"ok": True, "cancelled": True}
    await db.job_applications.delete_one({"id": app_id, "user_id": user["user_id"]})
    return {"ok": True}


@router.get("/applications/{app_id}/attachment")
async def application_attachment(app_id: str, user: dict = Depends(get_current_user)):
    app_doc = await get_owned("job_applications", app_id, user["user_id"])
    if not app_doc.get("attachment_path"):
        raise HTTPException(status_code=404, detail="No attachment")
    try:
        data, _ = get_object(app_doc["attachment_path"])
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not load attachment: {exc}")
    return Response(content=data, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="{app_doc.get("attachment_filename", "resume.pdf")}"'})


# ------------------------------------------------------------------ autopilot

@router.get("/autopilot")
async def get_autopilot(user: dict = Depends(get_current_user)):
    settings = await get_settings(user["user_id"])
    return {"autopilot": settings["autopilot"], "sent_today": await count_sent_today(user["user_id"])}


@router.put("/autopilot")
async def update_autopilot(body: AutopilotIn, user: dict = Depends(get_current_user)):
    settings = await get_settings(user["user_id"])
    autop = {**settings["autopilot"]}
    data = body.model_dump(exclude_none=True)
    if "mode" in data and data["mode"] not in ("manual", "approval", "auto"):
        raise HTTPException(status_code=400, detail="Unknown mode")
    for key, value in data.items():
        autop[key] = value
    await db.app_settings.update_one({"user_id": user["user_id"]},
                                     {"$set": {"autopilot": autop}}, upsert=True)
    return {"autopilot": autop, "sent_today": await count_sent_today(user["user_id"])}


@router.post("/autopilot/emergency-stop")
async def emergency_stop(user: dict = Depends(get_current_user)):
    await db.app_settings.update_one({"user_id": user["user_id"]},
                                     {"$set": {"autopilot.paused": True}}, upsert=True)
    await add_event(user["user_id"], None, "autopilot_paused", "Emergency stop triggered by user")
    from mailer import notify_user
    if user.get("email"):
        await notify_user(user, "autopilot_paused", {"reason": "Emergency stop was triggered. No emails will be sent automatically until you resume Auto-Pilot."})
    return {"ok": True}


@router.post("/autopilot/run-now")
async def autopilot_run_now(user: dict = Depends(get_current_user)):
    from application_engine import run_autopilot_cycle
    summary = await run_autopilot_cycle(user["user_id"])
    return summary
