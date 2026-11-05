"""Core application engine: sending, events, and the background cycles
(auto-pilot, reply scanning, follow-ups) used by both API routes and crons."""

import asyncio
from contextlib import suppress
import logging
import re
from datetime import datetime, timedelta, timezone

from pymongo import ReturnDocument

from db import db, utc_now_iso, parse_iso
from mailer import notify_user
from storage import get_object
import gmail_service
import ai_service

logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

DISPOSABLE_DOMAINS = {
    "mailinator.com", "tempmail.com", "10minutemail.com", "guerrillamail.com",
    "yopmail.com", "trashmail.com", "sharklasers.com", "getnada.com",
}


def email_is_valid(email: str) -> bool:
    if not email or not EMAIL_RE.match(email):
        return False
    domain = email.split("@")[-1].lower()
    return domain not in DISPOSABLE_DOMAINS


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


async def add_event(user_id: str, application_id: str | None, event_type: str, detail: str = "",
                    meta: dict | None = None) -> dict:
    event = {
        "id": __import__("uuid").uuid4().hex,
        "user_id": user_id,
        "application_id": application_id,
        "type": event_type,
        "detail": detail,
        "meta": meta or {},
        "created_at": utc_now_iso(),
    }
    await db.application_events.insert_one(event.copy())
    return event


async def get_settings(user_id: str) -> dict:
    DEFAULTS = {
        "ai_model": "gpt-5.4",
        "email_tone": "professional",
        "autopilot": {
            "enabled": False, "mode": "approval", "max_per_day": 10,
            "min_delay_minutes": 30, "max_retries": 2, "min_match_score": 60, "paused": False,
        },
        "followups": {"enabled": True, "days": 4},
        "interviews": {"reminder_hours": 24},
        "digest": {"enabled": True, "hour": 8, "timezone": "UTC"},
        "notifications": {"application_sent": True, "reply_received": True,
                          "followup_ready": True, "send_failed": True, "interview_reminder": True},
    }
    doc = await db.app_settings.find_one({"user_id": user_id}, {"_id": 0})
    if not doc:
        return DEFAULTS
    for section in ("autopilot", "followups", "notifications", "interviews", "digest"):
        if isinstance(doc.get(section), dict):
            doc[section] = {**DEFAULTS[section], **doc[section]}
    return {**DEFAULTS, **doc}


async def count_sent_today(user_id: str) -> int:
    day_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return await db.job_applications.count_documents({
        "user_id": user_id, "status": "sent",
        "sent_at": {"$gte": day_start.isoformat()},
    })


async def duplicate_application_exists(user_id: str, hr_email: str, job_title: str,
                                       exclude_id: str | None = None) -> bool:
    query = {
        "user_id": user_id,
        "hr_email": normalize(hr_email),
        "job_title_norm": normalize(job_title),
        "status": {"$nin": ["cancelled", "send_failed"]},
    }
    if exclude_id:
        query["id"] = {"$ne": exclude_id}
    return await db.job_applications.count_documents(query) > 0


async def cleanup_stuck_sending_applications(user_id: str | None = None) -> int:
    """If the process dies mid-send, applications stay in 'sending'.
    Move any claims older than 10 minutes to 'needs_attention' with a note to check Gmail Sent."""
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    query = {"status": "sending", "sending_at": {"$lt": cutoff}}
    if user_id:
        query["user_id"] = user_id
    note = "Sending timed out after 10 minutes. Please check your Gmail Sent folder before retrying."
    stuck_docs = await db.job_applications.find(query, {"_id": 0, "id": 1, "user_id": 1}).to_list(100)
    for doc in stuck_docs:
        await db.job_applications.update_one(
            {"id": doc["id"], "user_id": doc["user_id"]},
            {"$set": {"status": "needs_attention", "error": note}},
        )
        await add_event(doc["user_id"], doc["id"], "needs_attention", note)
    return len(stuck_docs)


async def send_application(user_id: str, app_doc: dict, trigger: str = "manual",
                           allowed_statuses: list[str] | None = None) -> dict:
    """Send an application email through the user's connected Gmail with the exact
    resume version snapshot attached. Claims the application atomically to prevent duplicate sends.
    Returns {"ok": bool, "error": str|None}."""
    if app_doc.get("status") == "sent":
        return {"ok": False, "error": "Application was already sent"}
    if app_doc.get("channel") == "board":
        return {"ok": False, "error": "Job board applications are submitted by the ApplyPilot browser helper"}

    SENDABLE_STATUSES = ["draft", "awaiting_approval", "approved", "queued_auto"]
    claim_statuses = allowed_statuses if allowed_statuses else SENDABLE_STATUSES
    now_iso = utc_now_iso()

    # Atomically claim the application
    claimed = await db.job_applications.find_one_and_update(
        {"id": app_doc["id"], "user_id": user_id, "status": {"$in": claim_statuses}},
        {"$set": {
            "status": "sending",
            "previous_status": app_doc.get("status"),
            "sending_at": now_iso,
        }},
        return_document=ReturnDocument.AFTER,
    )
    if not claimed:
        return {"ok": False, "error": "Application is already being sent or cannot be sent from current status"}

    settings = await get_settings(user_id)
    autop = settings.get("autopilot", {})
    max_retries = int(autop.get("max_retries", 2))
    retries = int(claimed.get("retries", 0))

    async def _handle_failure(err_msg: str) -> dict:
        nonlocal retries
        retries += 1
        prev_status = claimed.get("previous_status") or "approved"
        new_status = "send_failed" if retries >= max_retries else prev_status
        await db.job_applications.update_one(
            {"id": app_doc["id"], "user_id": user_id},
            {"$set": {"status": new_status, "retries": retries, "error": err_msg[:300]}},
        )
        await add_event(
            user_id, app_doc["id"],
            "send_failed" if new_status == "send_failed" else "send_attempt_failed",
            err_msg[:200],
            {"retries": retries, "max_retries": max_retries, "status": new_status},
        )
        return {"ok": False, "error": err_msg[:200], "status": new_status, "retries": retries}

    if not email_is_valid(app_doc.get("hr_email", "")):
        return await _handle_failure(f"Invalid recipient email: {app_doc.get('hr_email', '')}")

    conn = await db.gmail_connections.find_one({"user_id": user_id}, {"_id": 0})
    if not conn or conn.get("status") == "reauth_required" or not conn.get("email"):
        return await _handle_failure("Gmail is not connected or re-authentication is required")

    attachment = None
    if app_doc.get("attachment_path"):
        try:
            attachment, _ = await asyncio.to_thread(get_object, app_doc["attachment_path"])
        except Exception as exc:
            return await _handle_failure(f"Resume attachment unavailable: {exc}")
    else:
        return await _handle_failure("No resume attached to this application")

    try:
        message_id, thread_id = await gmail_service.send_gmail_email(
            user_id=user_id,
            to=app_doc["hr_email"],
            subject=app_doc["subject"],
            body_text=app_doc.get("body_text", ""),
            attachment_bytes=attachment,
            attachment_filename=app_doc.get("attachment_filename") or "resume.pdf",
            reply_to=conn["email"],
        )
    except Exception as exc:
        return await _handle_failure(str(exc))

    # Right after Gmail returns a message id, write status "sent" immediately.
    # If that DB write fails, log the message id and never revert to a retryable status.
    sent_iso = utc_now_iso()
    try:
        await db.job_applications.update_one(
            {"id": app_doc["id"], "user_id": user_id},
            {"$set": {
                "status": "sent",
                "sent_at": sent_iso,
                "message_id": message_id,
                "thread_id": thread_id,
                "gmail_email": conn["email"],
                "error": None,
                "retries": 0,
            }},
        )
    except Exception as db_exc:
        logger.critical(
            "CRITICAL: Failed to record 'sent' status in DB after Gmail sent email! "
            "message_id=%s thread_id=%s app_id=%s user_id=%s exc=%s",
            message_id, thread_id, app_doc["id"], user_id, db_exc,
        )
        with suppress(Exception):
            await db.job_applications.update_one(
                {"id": app_doc["id"], "user_id": user_id},
                {"$set": {
                    "status": "needs_attention",
                    "message_id": message_id,
                    "thread_id": thread_id,
                    "error": f"Email was sent via Gmail (message_id: {message_id}) but DB update failed: {db_exc}",
                }},
            )
        return {"ok": True, "warning": "Email sent but DB update failed", "message_id": message_id}

    await add_event(user_id, app_doc["id"], "application_sent",
                    f"Sent to {app_doc['hr_email']} via Gmail ({trigger})",
                    {"company": app_doc.get("company", ""), "resume": app_doc.get("resume_name", "")})
    user = await db.users.find_one({"user_id": user_id}, {"_id": 0}) or {}
    if settings.get("notifications", {}).get("application_sent") and user.get("email"):
        await notify_user(user, "application_sent", {
            "company": app_doc.get("company", ""), "role": app_doc.get("job_title", ""),
            "resume": app_doc.get("resume_name", "")})
    return {"ok": True, "message_id": message_id}


# ---------------------------------------------------------------- auto-pilot

async def run_autopilot_cycle(user_id: str | None = None) -> dict:
    summary = {"users": 0, "sent": 0, "skipped": 0, "failed": 0}

    # Clean up any stale claims older than 10 minutes
    await cleanup_stuck_sending_applications(user_id)

    # Autopilot still needs enabled=true and paused=false. "Run cycle now" follows the same rules.
    query = {"autopilot.enabled": True, "autopilot.paused": False}
    if user_id:
        query["user_id"] = user_id

    async for settings in db.app_settings.find(query, {"_id": 0}):
        uid = settings["user_id"]
        autop = settings.get("autopilot", {})
        mode = autop.get("mode", "approval")

        # Manual mode: send nothing automatically
        if mode == "manual":
            summary["skipped"] += 1
            continue
        elif mode == "approval":
            allowed_statuses = ["approved"]
        elif mode == "auto":
            allowed_statuses = ["approved", "queued_auto"]
        else:
            summary["skipped"] += 1
            continue

        conn = await db.gmail_connections.find_one({"user_id": uid}, {"_id": 0})
        # Autopilot must skip users whose connection is "reauth_required"
        if not conn or conn.get("status") == "reauth_required" or conn.get("status") != "connected":
            summary["skipped"] += 1
            continue

        summary["users"] += 1
        max_per_day = int(autop.get("max_per_day", 10))
        sent_today = await count_sent_today(uid)
        remaining = max_per_day - sent_today
        if remaining <= 0:
            summary["skipped"] += 1
            continue

        min_delay_min = float(autop.get("min_delay_minutes", 30))
        if min_delay_min > 0:
            last_sent = await db.job_applications.find_one(
                {"user_id": uid, "status": "sent"}, {"_id": 0, "sent_at": 1}, sort=[("sent_at", -1)])
            if last_sent and last_sent.get("sent_at"):
                minutes_since = (datetime.now(timezone.utc) - parse_iso(last_sent["sent_at"])).total_seconds() / 60
                if minutes_since < min_delay_min:
                    summary["skipped"] += 1
                    continue

        candidates = await db.job_applications.find(
            {"user_id": uid, "status": {"$in": allowed_statuses}, "channel": {"$ne": "board"}}, {"_id": 0},
        ).sort("created_at", 1).to_list(remaining)

        failures = 0
        min_score = int(autop.get("min_match_score", 60))

        for app_doc in candidates:
            # Enforce daily cap inside the loop
            sent_today = await count_sent_today(uid)
            if sent_today >= max_per_day:
                summary["skipped"] += 1
                break

            # Enforce min_delay between sends inside a single cycle too
            if min_delay_min > 0:
                last_sent = await db.job_applications.find_one(
                    {"user_id": uid, "status": "sent"}, {"_id": 0, "sent_at": 1}, sort=[("sent_at", -1)])
                if last_sent and last_sent.get("sent_at"):
                    minutes_since = (datetime.now(timezone.utc) - parse_iso(last_sent["sent_at"])).total_seconds() / 60
                    if minutes_since < min_delay_min:
                        summary["skipped"] += 1
                        break

            # Score gating applies only to "queued_auto" items. Hand-approved items send regardless of score.
            if app_doc.get("status") == "queued_auto":
                if int(app_doc.get("match_score", 0)) < min_score:
                    continue

            if not email_is_valid(app_doc.get("hr_email", "")):
                await db.job_applications.update_one(
                    {"id": app_doc["id"], "user_id": uid},
                    {"$set": {"status": "send_failed", "error": "Invalid recipient email (blocked by auto-pilot)"}})
                await add_event(uid, app_doc["id"], "send_failed", "Invalid recipient email (auto-pilot)")
                summary["failed"] += 1
                continue

            result = await send_application(uid, app_doc, trigger="auto-pilot", allowed_statuses=allowed_statuses)
            if result["ok"]:
                summary["sent"] += 1
            else:
                summary["failed"] += 1
                failures += 1
                if result.get("status") == "send_failed":
                    user = await db.users.find_one({"user_id": uid}, {"_id": 0}) or {}
                    if settings.get("notifications", {}).get("send_failed") and user.get("email"):
                        await notify_user(user, "send_failed", {
                            "company": app_doc.get("company", ""), "error": result["error"]})

        if failures >= 3:
            await db.app_settings.update_one(
                {"user_id": uid}, {"$set": {"autopilot.paused": True}})
            user = await db.users.find_one({"user_id": uid}, {"_id": 0}) or {}
            await add_event(uid, None, "autopilot_paused", "Auto-pilot paused after repeated send failures")
            if user.get("email"):
                await notify_user(user, "autopilot_paused", {
                    "reason": "Auto-Pilot was paused after repeated send failures."})
    return summary


# ------------------------------------------------------------ reply scanning

async def run_reply_scan_cycle(user_id: str | None = None) -> dict:
    summary = {"users": 0, "scanned": 0, "replies": 0}
    query = {}
    if user_id:
        query["user_id"] = user_id
    async for conn in db.gmail_connections.find(query, {"_id": 0}):
        uid = conn["user_id"]
        summary["users"] += 1
        apps = await db.job_applications.find(
            {"user_id": uid, "status": {"$in": ["sent", "followed_up"]}},
            {"_id": 0, "id": 1, "hr_email": 1, "company": 1, "job_title": 1, "thread_id": 1},
        ).to_list(500)
        if not apps:
            continue
        state = await db.reply_scan_state.find_one({"user_id": uid}, {"_id": 0}) or {"processed": []}
        processed = set(state.get("processed", []))
        by_email = {normalize(a["hr_email"]): a for a in apps if a.get("hr_email")}
        by_thread = {a.get("thread_id"): a for a in apps if a.get("thread_id")}
        messages = await gmail_service.list_recent_inbox(uid, days=14, max_results=40)
        settings = await get_settings(uid)
        user = await db.users.find_one({"user_id": uid}, {"_id": 0}) or {}
        new_processed = []
        for msg in messages:
            if msg["id"] in processed:
                continue
            from_value = (msg.get("from") or "").lower()
            match = re.search(r"<([^>]+)>", from_value)
            sender_email = match.group(1) if match else from_value.strip()
            app_doc = by_thread.get(msg.get("thread_id")) or by_email.get(normalize(sender_email))
            if not app_doc:
                continue
            body = await gmail_service.get_message_text(uid, msg["id"])
            classification = await ai_service.classify_reply(msg.get("subject", ""), body) or {}
            processed.add(msg["id"])
            new_processed.append(msg["id"])
            summary["scanned"] += 1
            category = classification.get("category", "other")
            if category in ("interview", "interested", "rejection"):
                status_map = {"interview": "interview", "interested": "replied", "rejection": "rejected"}
                await db.job_applications.update_one(
                    {"id": app_doc["id"], "user_id": uid},
                    {"$set": {"status": status_map[category], "latest_response": classification.get("summary", ""),
                              "replied_at": utc_now_iso()}})
                await db.follow_ups.update_many(
                    {"user_id": uid, "application_id": app_doc["id"], "status": "pending"},
                    {"$set": {"status": "cancelled"}})
                await add_event(uid, app_doc["id"], "reply_received",
                                f"{category}: {classification.get('summary', '')}",
                                {"category": category, "from": msg.get("from", ""),
                                 "subject": msg.get("subject", ""), "next_action": classification.get("next_action", "")})
                summary["replies"] += 1
                if settings.get("notifications", {}).get("reply_received") and user.get("email"):
                    await notify_user(user, "reply_received", {
                        "company": app_doc.get("company", ""), "role": app_doc.get("job_title", ""),
                        "summary": classification.get("summary", "")})
        if new_processed:
            await db.reply_scan_state.update_one(
                {"user_id": uid},
                {"$set": {"processed": list(processed)[-500:], "updated_at": utc_now_iso()}}, upsert=True)
    return summary


# ------------------------------------------------------------- interview reminders

async def run_interview_reminder_cycle(user_id: str | None = None) -> dict:
    summary = {"reminders": 0}
    now = datetime.now(timezone.utc)
    query = {"status": "interview", "interview_at": {"$gte": now.isoformat()},
             "interview_reminder_sent": {"$ne": True}}
    if user_id:
        query["user_id"] = user_id
    apps = await db.job_applications.find(query, {"_id": 0}).to_list(500)
    for app_doc in apps:
        uid = app_doc["user_id"]
        settings = await get_settings(uid)
        lead = int(settings.get("interviews", {}).get("reminder_hours", 24))
        when = parse_iso(app_doc.get("interview_at"))
        if not when:
            continue
        if (when - now).total_seconds() / 3600 > lead:
            continue
        await db.job_applications.update_one(
            {"id": app_doc["id"], "user_id": uid},
            {"$set": {"interview_reminder_sent": True}})
        await add_event(uid, app_doc["id"], "interview_reminder",
                        f"Reminder: interview with {app_doc.get('company', '')} at {when.strftime('%d %b %H:%M UTC')}")
        summary["reminders"] += 1
        if settings.get("notifications", {}).get("interview_reminder", True):
            user = await db.users.find_one({"user_id": uid}, {"_id": 0}) or {}
            if user.get("email"):
                await notify_user(user, "interview_reminder", {
                    "company": app_doc.get("company", ""),
                    "when": when.strftime("%d %b %Y %H:%M UTC"),
                    "notes": app_doc.get("interview_notes", "")})
    return summary


# ------------------------------------------------------------- daily board digest

async def send_board_digest(uid: str, settings: dict, since: str | None) -> tuple[int, bool]:
    query = {"user_id": uid, "channel": "board", "status": {"$in": ["awaiting_approval", "draft"]}}
    if since:
        query["created_at"] = {"$gt": since}
    apps = await db.job_applications.find(query, {"_id": 0, "body_text": 0}).sort("match_score", -1).to_list(50)
    user = await db.users.find_one({"user_id": uid}, {"_id": 0}) or {}
    sent = False
    if apps and user.get("email"):
        sent = bool(await notify_user(user, "board_digest", {"apps": apps}))
    return len(apps), sent


async def run_board_digest_cycle(user_id: str | None = None, force: bool = False) -> dict:
    from zoneinfo import ZoneInfo
    summary = {"users": 0, "emails": 0}
    query = {"user_id": user_id} if user_id else {}
    async for doc in db.users.find(query, {"_id": 0, "user_id": 1}):
        uid = doc["user_id"]
        settings = await get_settings(uid)
        digest = settings["digest"]
        if not force and not digest.get("enabled"):
            continue
        try:
            tz = ZoneInfo(digest.get("timezone") or "UTC")
        except Exception:
            tz = timezone.utc
        local = datetime.now(tz)
        today = local.date().isoformat()
        if not force and (local.hour != int(digest.get("hour", 8)) or digest.get("last_sent_date") == today):
            continue
        summary["users"] += 1
        count, sent = await send_board_digest(uid, settings, digest.get("last_sent_at"))
        if count and not sent:
            logger.warning("Board digest email failed for a user; will retry next hour")
            continue
        if count:
            summary["emails"] += 1
            await add_event(uid, None, "board_digest", f"Daily digest emailed: {count} board job{'s' if count != 1 else ''} waiting for approval")
        await db.app_settings.update_one({"user_id": uid}, {"$set": {
            "digest.last_sent_date": today, "digest.last_sent_at": utc_now_iso()}}, upsert=True)
        summary["last_count"] = count
    return summary


# ---------------------------------------------------------------- follow-ups

async def run_followup_cycle(user_id: str | None = None) -> dict:
    summary = {"users": 0, "created": 0}
    query = {"followups.enabled": True}
    if user_id:
        query["user_id"] = user_id
    async for settings in db.app_settings.find(query, {"_id": 0}):
        uid = settings["user_id"]
        conn = await db.gmail_connections.find_one({"user_id": uid}, {"_id": 0})
        if not conn:
            continue
        summary["users"] += 1
        days = int(settings.get("followups", {}).get("days", 4))
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        apps = await db.job_applications.find(
            {"user_id": uid, "status": {"$in": ["sent", "followed_up"]}, "sent_at": {"$lt": cutoff}},
            {"_id": 0}).to_list(500)
        for app_doc in apps:
            replied = await db.application_events.count_documents(
                {"user_id": uid, "application_id": app_doc["id"], "type": "reply_received"})
            if replied:
                continue
            pending = await db.follow_ups.count_documents(
                {"user_id": uid, "application_id": app_doc["id"], "status": {"$in": ["pending", "sent"]}})
            if pending:
                continue
            days_since = (datetime.now(timezone.utc) - parse_iso(app_doc["sent_at"])).days
            draft = await ai_service.generate_followup_email({
                "company_name": app_doc.get("company", ""),
                "job_title": app_doc.get("job_title", ""),
                "original_subject": app_doc.get("subject", ""),
                "days_since": days_since,
                "tone": settings.get("email_tone", "professional"),
                "candidate_name": (await db.users.find_one({"user_id": uid}, {"_id": 0}) or {}).get("name", ""),
            })
            if not draft:
                continue
            followup = {
                "id": __import__("uuid").uuid4().hex,
                "user_id": uid,
                "application_id": app_doc["id"],
                "company": app_doc.get("company", ""),
                "job_title": app_doc.get("job_title", ""),
                "hr_email": app_doc.get("hr_email", ""),
                "subject": draft.get("subject", "Following up on my application"),
                "body_text": draft.get("body", ""),
                "status": "pending",
                "due_at": utc_now_iso(),
                "created_at": utc_now_iso(),
            }
            await db.follow_ups.insert_one(followup.copy())
            await add_event(uid, app_doc["id"], "followup_draft_created",
                            f"Follow-up draft ready for {app_doc.get('company', '')}")
            await db.job_applications.update_one(
                {"id": app_doc["id"], "user_id": uid},
                {"$set": {"next_followup_at": followup["due_at"]}})
            summary["created"] += 1
            if settings.get("notifications", {}).get("followup_ready"):
                user = await db.users.find_one({"user_id": uid}, {"_id": 0}) or {}
                if user.get("email"):
                    await notify_user(user, "followup_ready", {
                        "company": app_doc.get("company", "")})
    return summary
