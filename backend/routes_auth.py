import logging
from pydantic import BaseModel, EmailStr
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from db import db, utc_now_iso
from deps import get_current_user
from auth import (
    OWNER_USER_ID,
    COOKIE_NAME,
    SESSION_EXPIRY_SECONDS,
    get_owner_email,
    get_owner_password_hash,
    is_secure_cookie,
    check_login_lockout,
    record_login_failure,
    record_login_success,
    verify_password,
    create_session_token,
)

logger = logging.getLogger("applypilot.auth")
router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    email: str
    password: str


@router.post("/login")
async def login(body: LoginIn, response: Response):
    # Check rate limit lockout first
    await check_login_lockout()

    owner_email = get_owner_email()
    owner_pwd_hash = get_owner_password_hash()

    input_email = (body.email or "").strip().lower()
    input_password = body.password or ""

    if not input_email or not input_password:
        await record_login_failure()
        raise HTTPException(status_code=400, detail="Email and password are required")

    # Single-user: owner email, default owner, or connected Gmail email
    conn = await db.gmail_connections.find_one({"user_id": OWNER_USER_ID})
    connected_email = (conn.get("email") or "").strip().lower() if conn else ""
    valid_emails = {owner_email, "owner@applypilot.dev"}
    if connected_email:
        valid_emails.add(connected_email)

    if input_email not in valid_emails or not verify_password(input_password, owner_pwd_hash):
        await record_login_failure()
        logger.warning("Failed login attempt for email: %s", input_email)
        raise HTTPException(status_code=401, detail="Invalid email or password")

    # Login successful: clear failure history
    await record_login_success()
    token = create_session_token(owner_email)

    # Set HttpOnly, SameSite=Lax session cookie (Secure in production)
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=SESSION_EXPIRY_SECONDS,
        httponly=True,
        samesite="lax",
        secure=is_secure_cookie(),
        path="/",
    )

    # Ensure user record exists in db.users
    user_doc = {
        "user_id": OWNER_USER_ID,
        "email": owner_email,
        "name": "Owner",
        "last_login_at": utc_now_iso(),
    }
    await db.users.update_one(
        {"user_id": OWNER_USER_ID},
        {"$set": user_doc, "$setOnInsert": {"created_at": utc_now_iso()}},
        upsert=True,
    )

    return {
        "ok": True,
        "user": {
            "user_id": OWNER_USER_ID,
            "email": owner_email,
            "name": "Owner",
        },
    }


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(
        key=COOKIE_NAME,
        httponly=True,
        samesite="lax",
        secure=is_secure_cookie(),
        path="/",
    )
    return {"ok": True}


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    return {
        "ok": True,
        "user": {
            "user_id": user.get("user_id", OWNER_USER_ID),
            "email": user.get("email", get_owner_email()),
            "name": user.get("name", "Owner"),
        },
    }
