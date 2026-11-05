from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends

from application_engine import get_settings, count_sent_today
from db import db, parse_iso, utc_now_iso
from deps import get_current_user

router = APIRouter(prefix="/api", tags=["dashboard"])

REPLY_STATUSES = {"replied", "interview", "offer"}
SUCCESS_STATUSES = {"replied", "interview", "offer"}


@router.get("/dashboard")
async def dashboard(user: dict = Depends(get_current_user)):
    uid = user["user_id"]
    apps = await db.job_applications.find(
        {"user_id": uid}, {"_id": 0, "status": 1, "created_at": 1, "sent_at": 1, "company": 1}).to_list(5000)
    status_counts = {}
    for a in apps:
        status_counts[a.get("status", "unknown")] = status_counts.get(a.get("status", "unknown"), 0) + 1
    sent = sum(status_counts.get(s, 0) for s in ("sent", "followed_up", "replied", "interview", "rejected", "offer"))
    replies = sum(status_counts.get(s, 0) for s in REPLY_STATUSES)
    success_rate = round(100 * replies / sent) if sent else 0

    per_day = []
    for offset in range(13, -1, -1):
        day = (datetime.now(timezone.utc) - timedelta(days=offset)).date()
        day_apps = [a for a in apps if (parse_iso(a.get("sent_at")) or parse_iso(a.get("created_at")) or
                                        datetime.now(timezone.utc)).date() == day]
        per_day.append({
            "date": day.isoformat(),
            "applications": len(day_apps),
            "sent": len([a for a in day_apps if a.get("sent_at")]),
        })

    role_counts = {}
    app_titles = await db.job_applications.find(
        {"user_id": uid, "role_profile_title": {"$exists": True}},
        {"_id": 0, "role_profile_title": 1}).to_list(5000)
    for app_doc in app_titles:
        title = app_doc.get("role_profile_title") or "Other"
        role_counts[title] = role_counts.get(title, 0) + 1

    recent_events = await db.application_events.find({"user_id": uid}, {"_id": 0}) \
        .sort("created_at", -1).limit(15).to_list(15)
    upcoming = await db.job_applications.find(
        {"user_id": uid, "status": "interview", "interview_at": {"$gte": utc_now_iso()}},
        {"_id": 0, "company": 1, "job_title": 1, "interview_at": 1, "interview_notes": 1},
    ).sort("interview_at", 1).limit(3).to_list(3)
    settings = await get_settings(uid)
    return {
        "stats": {
            "total_applications": len(apps),
            "emails_sent": sent,
            "pending": sum(status_counts.get(s, 0) for s in
                           ("draft", "awaiting_approval", "queued_auto", "scheduled", "approved")),
            "hr_replies": status_counts.get("replied", 0),
            "interviews": status_counts.get("interview", 0),
            "failed": status_counts.get("send_failed", 0),
            "success_rate": success_rate,
        },
        "status_distribution": [{"status": s, "count": c} for s, c in status_counts.items()],
        "per_day": per_day,
        "role_distribution": [{"role": r, "count": c} for r, c in
                              sorted(role_counts.items(), key=lambda kv: -kv[1])[:6]],
        "recent_activity": recent_events,
        "upcoming_interviews": upcoming,
        "counters": {
            "role_profiles": await db.role_profiles.count_documents({"user_id": uid}),
            "hr_contacts": await db.hr_contacts.count_documents({"user_id": uid}),
            "opportunities": await db.job_opportunities.count_documents({"user_id": uid}),
            "followups_pending": await db.follow_ups.count_documents({"user_id": uid, "status": "pending"}),
            "sent_today": await count_sent_today(uid),
            "daily_limit": settings.get("autopilot", {}).get("max_per_day", 10),
        },
        "autopilot": settings.get("autopilot", {}),
        "gmail_connected": bool(await db.gmail_connections.find_one({"user_id": uid, "status": "connected"}, {"_id": 0})),
    }
