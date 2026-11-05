from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from application_engine import get_settings
from crypto import encrypt
from db import db, utc_now_iso
from deps import get_current_user
from mailer import send_email

router = APIRouter(prefix="/api", tags=["settings"])

MODELS = ["gpt-5.4", "gpt-5.6-terra", "gpt-5.5", "claude-sonnet-5-5", "gemini-3.1-pro-preview"]
TONES = ["professional", "warm", "direct", "enthusiastic"]


class AutopilotIn(BaseModel):
    enabled: Optional[bool] = None
    mode: Optional[Literal["manual", "approval", "auto"]] = None
    max_per_day: Optional[int] = Field(None, ge=1, le=50)
    min_delay_minutes: Optional[int] = Field(None, ge=1, le=1440)
    max_retries: Optional[int] = Field(None, ge=0, le=5)
    min_match_score: Optional[int] = Field(None, ge=0, le=100)
    paused: Optional[bool] = None


class FollowupsIn(BaseModel):
    enabled: Optional[bool] = None
    days: Optional[int] = Field(None, ge=1, le=30)


class InterviewsIn(BaseModel):
    reminder_hours: Optional[int] = Field(None, ge=1, le=168)


class NotificationsIn(BaseModel):
    application_sent: Optional[bool] = None
    reply_received: Optional[bool] = None
    followup_ready: Optional[bool] = None
    send_failed: Optional[bool] = None
    interview_reminder: Optional[bool] = None


class DigestIn(BaseModel):
    enabled: Optional[bool] = None
    hour: Optional[int] = Field(None, ge=0, le=23)
    timezone: Optional[str] = None


class SettingsIn(BaseModel):
    ai_model: Optional[str] = None
    email_tone: Optional[str] = None
    autopilot: Optional[AutopilotIn] = None
    followups: Optional[FollowupsIn] = None
    interviews: Optional[InterviewsIn] = None
    notifications: Optional[NotificationsIn] = None
    digest: Optional[DigestIn] = None


class GoogleOAuthIn(BaseModel):
    client_id: str
    client_secret: str


@router.get("/settings")
async def read_settings(user: dict = Depends(get_current_user)):
    settings = await get_settings(user["user_id"])
    cfg = await db.google_oauth_config.find_one({"user_id": user["user_id"]}, {"_id": 0})
    settings["models_available"] = MODELS
    settings["tones_available"] = TONES
    settings["google_oauth"] = {"configured": bool(cfg and cfg.get("client_id")),
                                "client_id": (cfg or {}).get("client_id", "")}
    settings["user"] = {"email": user.get("email", ""), "name": user.get("name", "")}
    return settings


@router.put("/settings")
async def write_settings(body: SettingsIn, user: dict = Depends(get_current_user)):
    settings = await get_settings(user["user_id"])
    data = body.model_dump(exclude_none=True)
    updates = {}
    if data.get("ai_model") is not None:
        if data["ai_model"] not in MODELS:
            raise HTTPException(status_code=400, detail="Unknown model")
        updates["ai_model"] = data["ai_model"]
    if data.get("email_tone") is not None:
        if data["email_tone"] not in TONES:
            raise HTTPException(status_code=400, detail="Unknown tone")
        updates["email_tone"] = data["email_tone"]
    for section, cls in (("autopilot", AutopilotIn), ("followups", FollowupsIn),
                         ("interviews", InterviewsIn), ("notifications", NotificationsIn), ("digest", DigestIn)):
        incoming = data.get(section)
        if incoming:
            merged = {**settings[section], **{k: v for k, v in incoming.items() if v is not None}}
            updates[section] = merged
    if "timezone" in (data.get("digest") or {}):
        from zoneinfo import available_timezones
        if updates["digest"]["timezone"] not in available_timezones():
            raise HTTPException(status_code=400, detail="Unknown timezone")
    if updates:
        updates["updated_at"] = utc_now_iso()
        await db.app_settings.update_one({"user_id": user["user_id"]}, {"$set": updates}, upsert=True)
    return await get_settings(user["user_id"])


@router.post("/settings/google-oauth")
async def save_google_oauth(body: GoogleOAuthIn, user: dict = Depends(get_current_user)):
    if not body.client_id.strip() or not body.client_secret.strip():
        raise HTTPException(status_code=400, detail="Client ID and secret are required")
    await db.google_oauth_config.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"client_id": encrypt(body.client_id.strip()),
                  "client_secret": encrypt(body.client_secret.strip()),
                  "updated_at": utc_now_iso()}},
        upsert=True)
    return {"ok": True, "client_id": body.client_id.strip()}


@router.post("/settings/digest/send-now")
async def digest_send_now(user: dict = Depends(get_current_user)):
    from application_engine import send_board_digest
    if not user.get("email"):
        raise HTTPException(status_code=400, detail="No verified email on your account")
    count, sent = await send_board_digest(user["user_id"], await get_settings(user["user_id"]), None)
    if count and not sent:
        raise HTTPException(status_code=502, detail="Digest email could not be sent right now")
    return {"ok": True, "jobs": count, "sent_to": user["email"] if sent else None}


@router.post("/settings/notifications/test")
async def test_notification(user: dict = Depends(get_current_user)):
    if not user.get("email"):
        raise HTTPException(status_code=400, detail="No verified email on your account")
    message_id = await send_email(
        to=user["email"],
        subject="ApplyPilot test notification",
        html='<p>This is a test notification from your ApplyPilot account. '
             'In-app notifications like HR replies, sent applications and follow-up '
             'reminders will arrive from this address.</p>')
    if not message_id:
        raise HTTPException(status_code=502, detail="Notification email could not be sent right now")
    return {"ok": True, "sent_to": user["email"]}
