import asyncio
import csv
import io
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from application_engine import add_event, email_is_valid, run_reply_scan_cycle
from db import db, utc_now_iso
from deps import get_current_user, get_owned

router = APIRouter(prefix="/api", tags=["tracking"])


class FollowUpIn(BaseModel):
    subject: Optional[str] = None
    body_text: Optional[str] = None


@router.get("/tracking/history")
async def history(search: str = "", user: dict = Depends(get_current_user)):
    query = {"user_id": user["user_id"], "dry_run": {"$ne": True}}
    if search.strip():
        rx = {"$regex": re.escape(search.strip()), "$options": "i"}
        query["$or"] = [{"company": rx}, {"job_title": rx}, {"hr_email": rx},
                        {"role_profile_title": rx}]
    docs = await db.job_applications.find(query, {"_id": 0, "body_text": 0}).sort("created_at", -1).to_list(500)
    return docs


@router.get("/tracking/export")
async def export_csv(user: dict = Depends(get_current_user)):
    docs = await db.job_applications.find({"user_id": user["user_id"], "dry_run": {"$ne": True}}, {"_id": 0, "body_text": 0}) \
        .sort("created_at", -1).to_list(1000)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Company", "Role", "HR Contact", "HR Email", "Application Date", "Status",
                     "Role Profile Used", "Resume Version Used", "Email Status", "Latest Response",
                     "Next Follow-up", "Match Score"])
    for d in docs:
        writer.writerow([
            d.get("company", ""), d.get("job_title", ""), d.get("hr_name", ""), d.get("hr_email", ""),
            d.get("sent_at") or d.get("created_at", ""), d.get("status", ""),
            d.get("role_profile_title", ""),
            f'{d.get("resume_name", "")} (v{d.get("resume_version_no", "")})' if d.get("resume_name") else "",
            d.get("status", ""), d.get("latest_response", ""), d.get("next_followup_at") or "", d.get("match_score", ""),
        ])
    buffer.seek(0)
    return StreamingResponse(iter([buffer.read()]), media_type="text/csv", headers={
        "Content-Disposition": 'attachment; filename="applypilot-applications.csv"'})


@router.get("/tracking/events")
async def events(application_id: str = "", limit: int = 50, user: dict = Depends(get_current_user)):
    query = {"user_id": user["user_id"]}
    if application_id:
        query["application_id"] = application_id
    docs = await db.application_events.find(query, {"_id": 0}).sort("created_at", -1).limit(min(limit, 200)).to_list(limit)
    return docs


@router.get("/followups")
async def list_followups(status: str = "", user: dict = Depends(get_current_user)):
    query = {"user_id": user["user_id"]}
    if status:
        query["status"] = status
    docs = await db.follow_ups.find(query, {"_id": 0}).sort("created_at", -1).to_list(200)
    return docs


@router.put("/followups/{followup_id}")
async def edit_followup(followup_id: str, body: FollowUpIn, user: dict = Depends(get_current_user)):
    followup = await get_owned("follow_ups", followup_id, user["user_id"])
    if followup.get("status") == "sent":
        raise HTTPException(status_code=400, detail="Sent follow-ups cannot be edited")
    updates = {}
    if body.subject is not None:
        updates["subject"] = body.subject.strip()[:300]
    if body.body_text is not None:
        updates["body_text"] = body.body_text[:20000]
    if updates:
        await db.follow_ups.update_one({"id": followup_id, "user_id": user["user_id"]}, {"$set": updates})
    return await db.follow_ups.find_one({"id": followup_id, "user_id": user["user_id"]}, {"_id": 0})


@router.post("/followups/{followup_id}/send")
async def send_followup(followup_id: str, user: dict = Depends(get_current_user)):
    uid = user["user_id"]
    followup = await get_owned("follow_ups", followup_id, uid)
    if followup.get("status") not in ("pending",):
        raise HTTPException(status_code=400, detail="Only pending follow-ups can be sent")
    app_doc = await db.job_applications.find_one({"id": followup["application_id"], "user_id": uid}, {"_id": 0})
    if not app_doc:
        raise HTTPException(status_code=404, detail="Original application not found")
    if not email_is_valid(followup.get("hr_email", "")):
        raise HTTPException(status_code=400, detail="Invalid recipient email")
    attachment = None
    if app_doc.get("attachment_path"):
        from storage import get_object
        try:
            attachment, _ = await asyncio.to_thread(get_object, app_doc["attachment_path"])
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Resume attachment unavailable: {exc}")
    import gmail_service
    try:
        message_id, thread_id = await gmail_service.send_gmail_email(
            user_id=uid, to=followup["hr_email"], subject=followup["subject"],
            body_text=followup.get("body_text", ""), attachment_bytes=attachment,
            attachment_filename=app_doc.get("attachment_filename"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Follow-up send failed: {exc}")
    await db.follow_ups.update_one({"id": followup_id, "user_id": uid},
                                   {"$set": {"status": "sent", "sent_at": utc_now_iso(),
                                             "message_id": message_id, "thread_id": thread_id}})
    await db.job_applications.update_one({"id": followup["application_id"], "user_id": uid},
                                         {"$set": {"status": "followed_up", "next_followup_at": None}})
    await add_event(uid, followup["application_id"], "followup_sent", f"Follow-up sent to {followup['hr_email']}")
    return {"ok": True}


@router.post("/followups/{followup_id}/cancel")
async def cancel_followup(followup_id: str, user: dict = Depends(get_current_user)):
    followup = await get_owned("follow_ups", followup_id, user["user_id"])
    await db.follow_ups.update_one({"id": followup_id, "user_id": user["user_id"]},
                                   {"$set": {"status": "cancelled"}})
    await db.job_applications.update_one({"id": followup["application_id"], "user_id": user["user_id"]},
                                         {"$set": {"next_followup_at": None}})
    return {"ok": True}


@router.delete("/followups/{followup_id}")
async def delete_followup(followup_id: str, user: dict = Depends(get_current_user)):
    followup = await get_owned("follow_ups", followup_id, user["user_id"])
    if followup.get("status") == "sent":
        raise HTTPException(status_code=400, detail="Sent follow-ups are kept for history")
    await db.follow_ups.delete_one({"id": followup_id, "user_id": user["user_id"]})
    return {"ok": True}


@router.post("/tracking/scan-replies")
async def scan_replies(user: dict = Depends(get_current_user)):
    conn = await db.gmail_connections.find_one({"user_id": user["user_id"]}, {"_id": 0})
    if not conn:
        raise HTTPException(status_code=400, detail="Connect your Gmail account first")
    summary = await run_reply_scan_cycle(user["user_id"])
    return summary
