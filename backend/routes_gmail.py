
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

import gmail_service
from application_engine import add_event
from db import db
from deps import get_current_user

router = APIRouter(prefix="/api", tags=["gmail"])


import os

def external_base_url(request: Request) -> str:
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme or "http"
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}"


def get_redirect_uri(request: Request) -> str:
    env_uri = os.environ.get("GOOGLE_REDIRECT_URI", "").strip()
    if env_uri:
        return env_uri
    return f"{external_base_url(request)}/api/gmail/callback"


@router.get("/gmail/status")
async def gmail_status(request: Request, user: dict = Depends(get_current_user)):
    conn = await db.gmail_connections.find_one({"user_id": user["user_id"]}, {"_id": 0})
    client_id, _ = await gmail_service.get_google_config(user["user_id"])
    if not conn:
        return {"connected": False, "status": "disconnected", "reauth_required": False,
                "google_configured": bool(client_id),
                "redirect_uri": get_redirect_uri(request)}
    conn_status = conn.get("status", "connected")
    return {
        "connected": conn_status == "connected",
        "status": conn_status,
        "reauth_required": conn_status == "reauth_required",
        "last_refresh_error": conn.get("last_refresh_error"),
        "email": conn.get("email", ""),
        "connected_at": conn.get("connected_at"),
        "scopes": conn.get("scopes", []),
        "google_configured": bool(client_id),
        "redirect_uri": get_redirect_uri(request),
    }


class StartIn(BaseModel):
    frontend_origin: str = ""


@router.post("/gmail/start")
async def gmail_start(body: StartIn, request: Request, user: dict = Depends(get_current_user)):
    client_id, _ = await gmail_service.get_google_config(user["user_id"])
    if not client_id:
        raise HTTPException(status_code=400, detail="google_not_configured")
    origin = body.frontend_origin.strip()
    if origin and not origin.startswith("http"):
        raise HTTPException(status_code=400, detail="Invalid origin")
    redirect_uri = get_redirect_uri(request)
    url = await gmail_service.start_flow(user["user_id"], redirect_uri, origin)
    if not url:
        raise HTTPException(status_code=502, detail="Could not start Google OAuth flow")
    return {"auth_url": url}


@router.get("/gmail/callback")
async def gmail_callback(code: str = "", state: str = "", error: str = ""):
    frontend_base = "http://localhost:3000"
    if state:
        st = await db.oauth_states.find_one({"state": state})
        if st and st.get("origin") and st["origin"].startswith("http"):
            frontend_base = st["origin"].rstrip("/")

    if error:
        return RedirectResponse(f"{frontend_base}/gmail?error={error}")
    if not code or not state:
        return RedirectResponse(f"{frontend_base}/gmail?error=missing_code")
    try:
        origin = await gmail_service.handle_callback(code, state)
        if origin and origin.startswith("http"):
            frontend_base = origin.rstrip("/")
    except HTTPException as exc:
        logger.error("Gmail OAuth callback HTTP error: %s", exc.detail)
        return RedirectResponse(f"{frontend_base}/gmail?error={exc.detail}")
    except Exception as exc:
        logger.exception("Gmail OAuth callback failed unexpectedly: %s", exc)
        return RedirectResponse(f"{frontend_base}/gmail?error=oauth_failed")
    return RedirectResponse(f"{frontend_base}/gmail?connected=1")


@router.post("/gmail/disconnect")
async def gmail_disconnect(user: dict = Depends(get_current_user)):
    await db.gmail_connections.delete_one({"user_id": user["user_id"]})
    await add_event(user["user_id"], None, "gmail_disconnected", "Gmail account disconnected")
    return {"ok": True}
