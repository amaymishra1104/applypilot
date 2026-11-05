"""Job boards: browser-helper connection, apply profile, automatic board search and board applications."""

import asyncio
import hashlib
import logging
import re
import secrets
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

import ai_service
import board_search
from application_engine import add_event, count_sent_today, email_is_valid, get_settings, normalize
from db import db, utc_now_iso, parse_iso
from deps import get_current_user, get_owned
from routes_opportunities import build_doc, run_match
from storage import get_object

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["boards"])

EMAIL_IN_TEXT = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
BOARD_STATUSES = ["draft", "awaiting_approval", "approved", "queued_auto", "submitting", "sent",
                  "needs_attention", "send_failed", "cancelled", "replied", "interview", "rejected", "offer"]


class ApplyProfileIn(BaseModel):
    full_name: str = ""
    email: str = ""
    phone: str = ""
    city: str = ""
    linkedin_url: str = ""
    github_url: str = ""
    portfolio_url: str = ""
    current_title: str = ""
    current_company: str = ""
    years_experience: str = ""
    notice_period: str = ""
    current_ctc: str = ""
    expected_ctc: str = ""
    work_authorization: str = ""
    willing_to_relocate: str = ""
    custom_answers: List[dict] = []


class SearchConfigIn(BaseModel):
    enabled: bool = False
    keywords: List[str] = []
    location: str = ""
    boards: List[str] = []
    max_new_per_run: int = 10


class ExtJobIn(BaseModel):
    url: str
    title: str = ""
    company: str = ""
    location: str = ""
    description: str = ""
    board: str = ""


class ExtResultIn(BaseModel):
    outcome: str
    detail: str = ""


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _norm_url(url: str) -> str:
    return re.sub(r"[?#].*$", "", (url or "").strip().lower()).rstrip("/")


async def ext_user(x_applypilot_token: str = Header(default="")) -> dict:
    if not x_applypilot_token:
        raise HTTPException(status_code=401, detail="Missing browser helper token")
    doc = await db.extension_tokens.find_one({"token_hash": _hash(x_applypilot_token), "revoked": {"$ne": True}},
                                            {"_id": 0})
    if not doc:
        raise HTTPException(status_code=401, detail="Browser helper token is invalid or revoked")
    await db.extension_tokens.update_one({"token_hash": doc["token_hash"]}, {"$set": {"last_used_at": utc_now_iso()}})
    user = await db.users.find_one({"user_id": doc["user_id"]}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=401, detail="Unknown user")
    return user


async def _board_settings(uid: str) -> dict:
    doc = await db.app_settings.find_one({"user_id": uid}, {"_id": 0, "apply_profile": 1, "board_search": 1}) or {}
    search = {"enabled": False, "keywords": [], "location": "", "boards": [], "max_new_per_run": 10,
              **(doc.get("board_search") or {})}
    return {"apply_profile": doc.get("apply_profile") or {}, "board_search": search}


# --------------------------------------------------------------- core pipeline

async def _upsert_contact_from_text(uid: str, company: str, text: str) -> Optional[str]:
    emails = [e for e in EMAIL_IN_TEXT.findall(text or "") if email_is_valid(e)]
    if not emails:
        return None
    email = normalize(emails[0])
    existing = await db.hr_contacts.find_one({"user_id": uid, "hr_email_norm": email}, {"_id": 0})
    if existing:
        return existing["id"]
    from routes_contacts import build_doc as build_contact
    contact = build_contact(uid, {"hr_email": email, "company_name": company, "notes": "Found in a job board posting"})
    await db.hr_contacts.insert_one(contact.copy())
    return contact["id"]


async def save_board_job(uid: str, job: dict, source: str) -> tuple[dict, bool]:
    url_norm = _norm_url(job["url"])
    existing = await db.job_opportunities.find_one({"user_id": uid, "job_url_norm": url_norm}, {"_id": 0})
    if existing:
        return existing, False
    contact_id = await _upsert_contact_from_text(uid, job.get("company", ""), job.get("description", ""))
    doc = build_doc(uid, {
        "company_name": job.get("company", ""), "job_title": job.get("title", ""),
        "job_description": job.get("description", ""), "required_skills": job.get("skills", []),
        "source": source, "hr_contact_id": contact_id,
    }, extra={"board": job.get("board") or board_search.board_from_url(job["url"]), "job_url": job["url"].strip(),
              "job_url_norm": url_norm, "location": job.get("location", "")})
    await db.job_opportunities.insert_one(doc.copy())
    await add_event(uid, None, "opportunity_added",
                    f"{board_search.BOARDS.get(doc['board'], {}).get('label', 'Job board')} job saved: {doc['job_title']}")
    return doc, True


async def create_board_application(uid: str, opp: dict, match: dict, user: dict) -> Optional[dict]:
    if await db.job_applications.find_one({"user_id": uid, "channel": "board", "job_url_norm": opp["job_url_norm"],
                                           "status": {"$ne": "cancelled"}}, {"_id": 0, "id": 1}):
        return None
    version = None
    if match.get("resume_version_id"):
        version = await db.resume_versions.find_one(
            {"id": match["resume_version_id"], "user_id": uid, "is_deleted": {"$ne": True}}, {"_id": 0})
    if not version:
        return None
    settings = await get_settings(uid)
    autop = settings["autopilot"]
    score = int(match.get("score", 0))
    if autop.get("mode") == "auto" and score >= int(autop.get("min_match_score", 60)):
        status = "queued_auto"
    elif autop.get("mode") == "manual":
        status = "draft"
    else:
        status = "awaiting_approval"
    letter = await ai_service.generate_application_email({
        "hr_name": "", "hr_email": "", "company_name": opp.get("company_name", ""),
        "job_title": opp.get("job_title", ""), "required_skills": opp.get("required_skills", []),
        "description_summary": opp.get("job_description", "")[:1500], "company_background": "",
        "role_title": match.get("role_profile_title", ""), "role_skills": [], "experience_required": "",
        "role_notes": "Write this as a short cover letter for a job board application form.",
        "matched_skills": match.get("matched_skills", []), "resume_text": version.get("resume_text", ""),
        "tone": settings.get("email_tone", "professional"), "candidate_name": user.get("name", ""),
    }, settings.get("ai_model")) or {}
    app_doc = {
        "id": uuid.uuid4().hex, "user_id": uid, "channel": "board", "board": opp.get("board", "other"),
        "job_url": opp.get("job_url", ""), "job_url_norm": opp["job_url_norm"],
        "opportunity_id": opp["id"], "match_id": match["id"], "company": opp.get("company_name", ""),
        "job_title": opp.get("job_title", ""), "job_title_norm": normalize(opp.get("job_title", "")),
        "hr_name": "", "hr_email": "", "role_profile_id": match["role_profile_id"],
        "role_profile_title": match.get("role_profile_title", ""), "resume_version_id": version["id"],
        "resume_version_no": version["version_no"], "resume_name": version["name"],
        "attachment_path": version["storage_path"], "attachment_filename": version.get("filename") or "resume.pdf",
        "attachment_size": version.get("size", 0), "match_score": score,
        "subject": f"Application for {opp.get('job_title', '')}", "body_text": letter.get("body", ""),
        "status": status, "retries": 0, "sent_at": None, "latest_response": "", "error": None,
        "created_at": utc_now_iso(),
    }
    await db.job_applications.insert_one(app_doc.copy())
    await add_event(uid, app_doc["id"], "draft_created",
                    f"Board application prepared for {app_doc['company'] or app_doc['job_title']} "
                    f"({app_doc['board']}, {score}% match)", {"status": status})
    return app_doc


async def process_board_job(uid: str, opp_id: str, min_score: Optional[int] = None) -> dict:
    user = await db.users.find_one({"user_id": uid}, {"_id": 0}) or {"user_id": uid}
    try:
        match = await run_match(opp_id, user=user)
    except HTTPException as exc:
        await db.job_opportunities.update_one({"id": opp_id, "user_id": uid}, {"$set": {"board_error": exc.detail}})
        return {"ok": False, "error": exc.detail}
    if min_score is not None and int(match.get("score", 0)) < min_score:
        return {"ok": True, "match": match, "application": None, "skipped": "below_min_score"}
    opp = await get_owned("job_opportunities", opp_id, uid)
    app_doc = await create_board_application(uid, opp, match, user)
    return {"ok": True, "match": match, "application": app_doc}


async def run_board_search_for_user(uid: str, trigger: str = "manual") -> dict:
    cfg = (await _board_settings(uid))["board_search"]
    keywords = [k for k in cfg.get("keywords", []) if k.strip()]
    if not keywords:
        keywords = [p["title"] for p in await db.role_profiles.find({"user_id": uid}, {"_id": 0, "title": 1}).to_list(5)]
    run = {"id": uuid.uuid4().hex, "user_id": uid, "trigger": trigger, "started_at": utc_now_iso(),
           "finished_at": None, "keywords": keywords, "boards": {}, "new_jobs": 0, "applications_created": 0,
           "status": "running"}
    await db.board_search_runs.insert_one(run.copy())
    autop = (await get_settings(uid))["autopilot"]
    min_score = int(autop.get("min_match_score", 60))
    budget = max(1, min(int(cfg.get("max_new_per_run", 10)), 25))
    for board in [b for b in cfg.get("boards", []) if b in board_search.SEARCHERS]:
        if budget <= 0:
            break
        stat = {"found": 0, "new": 0, "error": None}
        for kw in keywords:
            if budget <= 0:
                break
            jobs, err = await board_search.search_board(board, kw, cfg.get("location", ""), limit=8)
            stat["error"] = stat["error"] or err
            stat["found"] += len(jobs)
            for job in jobs:
                if budget <= 0 or not job.get("url") or not job.get("title"):
                    continue
                opp, created = await save_board_job(uid, job, "board_search")
                if not created:
                    continue
                stat["new"] += 1
                budget -= 1
                res = await process_board_job(uid, opp["id"], min_score=min_score)
                if res.get("application"):
                    run["applications_created"] += 1
        run["boards"][board] = stat
        run["new_jobs"] += stat["new"]
        await db.board_search_runs.update_one({"id": run["id"]}, {"$set": {"boards": run["boards"]}})
    await db.board_search_runs.update_one({"id": run["id"]}, {"$set": {
        "boards": run["boards"], "new_jobs": run["new_jobs"], "applications_created": run["applications_created"],
        "finished_at": utc_now_iso(), "status": "done"}})
    await add_event(uid, None, "board_search", f"Job board search found {run['new_jobs']} new jobs, "
                                               f"{run['applications_created']} applications prepared")
    return run


async def run_board_search_cycle() -> dict:
    summary = {"users": 0}
    async for s in db.app_settings.find({"board_search.enabled": True}, {"_id": 0, "user_id": 1}):
        summary["users"] += 1
        try:
            await run_board_search_for_user(s["user_id"], trigger="schedule")
        except Exception:
            logger.exception("Board search failed for a user")
    return summary


async def _safe_bg(coro):
    try:
        await coro
    except Exception:
        logger.exception("Board background task failed")


# --------------------------------------------------------------- web app routes

@router.get("/boards/overview")
async def boards_overview(user: dict = Depends(get_current_user)):
    uid = user["user_id"]
    cfg = await _board_settings(uid)
    token = await db.extension_tokens.find_one({"user_id": uid, "revoked": {"$ne": True}},
                                               {"_id": 0, "token_hash": 0}, sort=[("created_at", -1)])
    apps = await db.job_applications.find({"user_id": uid, "channel": "board"}, {"_id": 0, "body_text": 0}) \
        .sort("created_at", -1).to_list(300)
    opp_ids = [a["opportunity_id"] for a in apps]
    opps = {o["id"]: o for o in await db.job_opportunities.find(
        {"user_id": uid, "id": {"$in": opp_ids}}, {"_id": 0, "id": 1, "hr_contact_id": 1}).to_list(300)}
    for a in apps:
        a["has_hr_email"] = bool((opps.get(a["opportunity_id"]) or {}).get("hr_contact_id"))
    runs = await db.board_search_runs.find({"user_id": uid}, {"_id": 0}).sort("started_at", -1).to_list(5)
    settings = await get_settings(uid)
    return {"boards": board_search.BOARDS, "extension": token, **cfg, "applications": apps, "runs": runs,
            "autopilot": settings["autopilot"], "sent_today": await count_sent_today(uid)}


@router.post("/boards/extension-token")
async def create_extension_token(user: dict = Depends(get_current_user)):
    uid = user["user_id"]
    await db.extension_tokens.update_many({"user_id": uid}, {"$set": {"revoked": True}})
    token = "apx_" + secrets.token_urlsafe(32)
    await db.extension_tokens.insert_one({"user_id": uid, "token_hash": _hash(token), "created_at": utc_now_iso(),
                                          "last_used_at": None, "revoked": False})
    return {"token": token}


@router.delete("/boards/extension-token")
async def revoke_extension_token(user: dict = Depends(get_current_user)):
    await db.extension_tokens.update_many({"user_id": user["user_id"]}, {"$set": {"revoked": True}})
    return {"ok": True}


@router.put("/boards/apply-profile")
async def save_apply_profile(body: ApplyProfileIn, user: dict = Depends(get_current_user)):
    data = body.model_dump()
    data = {k: (v.strip()[:500] if isinstance(v, str) else v) for k, v in data.items()}
    data["custom_answers"] = [{"question": str(a.get("question", "")).strip()[:300],
                               "answer": str(a.get("answer", "")).strip()[:2000]}
                              for a in body.custom_answers if str(a.get("question", "")).strip()][:40]
    await db.app_settings.update_one({"user_id": user["user_id"]}, {"$set": {"apply_profile": data}}, upsert=True)
    return data


@router.put("/boards/search-config")
async def save_search_config(body: SearchConfigIn, user: dict = Depends(get_current_user)):
    data = body.model_dump()
    data["boards"] = [b for b in data["boards"] if b in board_search.SEARCHERS]
    data["keywords"] = [k.strip()[:80] for k in data["keywords"] if k.strip()][:10]
    data["max_new_per_run"] = max(1, min(int(data["max_new_per_run"]), 25))
    await db.app_settings.update_one({"user_id": user["user_id"]}, {"$set": {"board_search": data}}, upsert=True)
    return data


@router.post("/boards/search/run")
async def run_search_now(user: dict = Depends(get_current_user)):
    cfg = (await _board_settings(user["user_id"]))["board_search"]
    if not cfg.get("boards"):
        raise HTTPException(status_code=400, detail="Pick at least one board to search and save")
    running = await db.board_search_runs.find_one({"user_id": user["user_id"], "status": "running"}, {"_id": 0})
    if running and (datetime.now(timezone.utc) - parse_iso(running["started_at"])).total_seconds() < 900:
        raise HTTPException(status_code=409, detail="A search is already running")
    asyncio.create_task(_safe_bg(run_board_search_for_user(user["user_id"])))
    return {"ok": True, "started": True}


@router.post("/boards/applications/{app_id}/switch-to-email")
async def switch_to_email(app_id: str, user: dict = Depends(get_current_user)):
    from routes_applications import GenerateIn, generate_application
    app_doc = await get_owned("job_applications", app_id, user["user_id"])
    if app_doc.get("channel") != "board" or app_doc.get("status") in ("sent", "submitting", "cancelled"):
        raise HTTPException(status_code=400, detail="This board application can't be switched to email now")
    email_app = await generate_application(GenerateIn(opportunity_id=app_doc["opportunity_id"]), user=user)
    await db.job_applications.update_one({"id": app_id, "user_id": user["user_id"]},
                                         {"$set": {"status": "cancelled", "error": "Switched to email application"}})
    await add_event(user["user_id"], app_id, "status_changed", "Board application replaced by an email application")
    return email_app


@router.post("/boards/applications/{app_id}/prepare")
async def prepare_for_opportunity(app_id: str, user: dict = Depends(get_current_user)):
    """Create a board application for an existing board opportunity (app_id is the opportunity id)."""
    opp = await get_owned("job_opportunities", app_id, user["user_id"])
    if not opp.get("job_url_norm"):
        raise HTTPException(status_code=400, detail="This opportunity has no job board link")
    res = await process_board_job(user["user_id"], opp["id"])
    if not res["ok"]:
        raise HTTPException(status_code=400, detail=res["error"])
    if not res.get("application"):
        raise HTTPException(status_code=409, detail="A board application already exists or the matched role has no resume")
    return res["application"]


# --------------------------------------------------------------- browser helper routes

def _task_view(app_doc: dict) -> dict:
    keys = ("id", "board", "job_url", "company", "job_title", "status", "match_score", "resume_name",
            "resume_version_id", "attachment_filename", "body_text")
    return {k: app_doc.get(k) for k in keys}


@router.get("/ext/me")
async def ext_me(user: dict = Depends(ext_user)):
    cfg = await _board_settings(user["user_id"])
    settings = await get_settings(user["user_id"])
    return {"name": user.get("name", ""), "email": user.get("email", ""), "apply_profile": cfg["apply_profile"],
            "autopilot": settings["autopilot"]}


@router.post("/ext/jobs")
async def ext_save_job(body: ExtJobIn, user: dict = Depends(ext_user)):
    if not re.match(r"^https?://", body.url.strip()):
        raise HTTPException(status_code=400, detail="Invalid job link")
    if not body.title.strip() and not body.description.strip():
        raise HTTPException(status_code=400, detail="Could not read the job title or description on this page")
    job = {"url": body.url.strip(), "title": body.title or "Untitled job", "company": body.company,
           "location": body.location, "description": body.description,
           "board": body.board if body.board in board_search.BOARDS else board_search.board_from_url(body.url)}
    opp, created = await save_board_job(user["user_id"], job, "browser_helper")
    if created:
        asyncio.create_task(_safe_bg(process_board_job(user["user_id"], opp["id"])))
    return {"opportunity_id": opp["id"], "created": created}


@router.get("/ext/jobs/{opp_id}")
async def ext_job_status(opp_id: str, user: dict = Depends(ext_user)):
    uid = user["user_id"]
    opp = await get_owned("job_opportunities", opp_id, uid)
    match = await db.job_matches.find_one({"user_id": uid, "opportunity_id": opp_id}, {"_id": 0})
    app_doc = await db.job_applications.find_one({"user_id": uid, "opportunity_id": opp_id, "channel": "board"},
                                                 {"_id": 0})
    return {"job_title": opp.get("job_title"), "company": opp.get("company_name"), "error": opp.get("board_error"),
            "match": {"score": match["score"], "role": match["role_profile_title"]} if match else None,
            "application": _task_view(app_doc) if app_doc else None}


@router.get("/ext/context")
async def ext_context(url: str = "", user: dict = Depends(ext_user)):
    uid = user["user_id"]
    app_doc = await db.job_applications.find_one(
        {"user_id": uid, "channel": "board", "job_url_norm": _norm_url(url), "status": {"$ne": "cancelled"}},
        {"_id": 0}) if url else None
    resume = None
    if app_doc:
        resume = {"version_id": app_doc["resume_version_id"], "filename": app_doc["attachment_filename"]}
    else:
        v = await db.resume_versions.find_one({"user_id": uid, "active": True, "is_deleted": {"$ne": True}},
                                              {"_id": 0}, sort=[("created_at", -1)])
        if v:
            resume = {"version_id": v["id"], "filename": v.get("filename") or "resume.pdf"}
    cfg = await _board_settings(uid)
    return {"apply_profile": cfg["apply_profile"], "application": _task_view(app_doc) if app_doc else None,
            "resume": resume}


@router.get("/ext/resume/{version_id}")
async def ext_resume(version_id: str, user: dict = Depends(ext_user)):
    v = await db.resume_versions.find_one({"id": version_id, "user_id": user["user_id"], "is_deleted": {"$ne": True}},
                                          {"_id": 0})
    if not v:
        raise HTTPException(status_code=404, detail="Resume not found")
    try:
        data, _ = await asyncio.wait_for(asyncio.to_thread(get_object, v["storage_path"]), timeout=20)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not load resume: {str(exc)[:100]}")
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{v.get("filename") or "resume.pdf"}"'})


@router.get("/ext/tasks")
async def ext_tasks(user: dict = Depends(ext_user)):
    """Next board application the helper should submit, honoring pause, daily limit and delay."""
    uid = user["user_id"]
    autop = (await get_settings(uid))["autopilot"]
    if autop.get("paused"):
        return {"tasks": [], "reason": "Auto-Pilot is stopped (emergency stop)"}
    if await count_sent_today(uid) >= int(autop.get("max_per_day", 10)):
        return {"tasks": [], "reason": "Daily limit reached"}
    stale = datetime.now(timezone.utc).timestamp() - 1800
    async for s in db.job_applications.find({"user_id": uid, "channel": "board", "status": "submitting"},
                                            {"_id": 0, "id": 1, "submitting_at": 1, "previous_status": 1}):
        started = parse_iso(s.get("submitting_at"))
        if not started or started.timestamp() < stale:
            await db.job_applications.update_one({"id": s["id"], "user_id": uid},
                                                 {"$set": {"status": s.get("previous_status") or "approved"}})
    statuses = ["approved"]
    if autop.get("enabled") and autop.get("mode") == "auto":
        last = await db.job_applications.find_one({"user_id": uid, "status": "sent"}, {"_id": 0, "sent_at": 1},
                                                  sort=[("sent_at", -1)])
        mins = ((datetime.now(timezone.utc) - parse_iso(last["sent_at"])).total_seconds() / 60
                if last and last.get("sent_at") else 1e9)
        if mins >= float(autop.get("min_delay_minutes", 30)):
            statuses.append("queued_auto")
    doc = await db.job_applications.find_one({"user_id": uid, "channel": "board", "status": {"$in": statuses}},
                                             {"_id": 0}, sort=[("created_at", 1)])
    if not doc:
        return {"tasks": [], "reason": "Nothing to submit"}
    await db.job_applications.update_one({"id": doc["id"], "user_id": uid},
                                         {"$set": {"status": "submitting", "previous_status": doc["status"],
                                                   "submitting_at": utc_now_iso()}})
    return {"tasks": [_task_view(doc)]}


@router.post("/ext/applications/{app_id}/result")
async def ext_result(app_id: str, body: ExtResultIn, user: dict = Depends(ext_user)):
    uid = user["user_id"]
    app_doc = await get_owned("job_applications", app_id, uid)
    if app_doc.get("channel") != "board":
        raise HTTPException(status_code=400, detail="Not a board application")
    if app_doc.get("status") != "submitting":
        raise HTTPException(status_code=409, detail="This application is not being submitted right now")
    if body.outcome == "submitted":
        updates = {"status": "sent", "sent_at": utc_now_iso(), "error": None}
        event, detail = "application_sent", f"Submitted on {app_doc.get('board')} via browser helper"
    elif body.outcome in ("needs_attention", "failed"):
        updates = {"status": "needs_attention", "error": body.detail[:300] or "Needs your input on the job page"}
        event, detail = "needs_attention", updates["error"]
    else:
        raise HTTPException(status_code=400, detail="Unknown outcome")
    await db.job_applications.update_one({"id": app_id, "user_id": uid}, {"$set": updates})
    await add_event(uid, app_id, event, detail, {"company": app_doc.get("company", ""), "board": app_doc.get("board")})
    return {"ok": True}
