import asyncio
import base64
import logging
import os
from datetime import datetime, timedelta, timezone
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from db import db, utc_now_iso, parse_iso
from crypto import encrypt, decrypt

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]

logger = logging.getLogger(__name__)


async def get_google_config(user_id: str) -> tuple[str | None, str | None]:
    cfg = await db.google_oauth_config.find_one({"user_id": user_id}, {"_id": 0})
    if cfg and cfg.get("client_id") and cfg.get("client_secret"):
        return decrypt(cfg["client_id"]), decrypt(cfg["client_secret"])
    env_id, env_secret = os.environ.get("GOOGLE_CLIENT_ID"), os.environ.get("GOOGLE_CLIENT_SECRET")
    if env_id and env_secret:
        return env_id, env_secret
    return None, None


def _client_config(client_id: str, client_secret: str) -> dict:
    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }


async def start_flow(user_id: str, redirect_uri: str, frontend_origin: str) -> str | None:
    from google_auth_oauthlib.flow import Flow

    client_id, client_secret = await get_google_config(user_id)
    if not client_id or not client_secret:
        return None
    flow = Flow.from_client_config(_client_config(client_id, client_secret), scopes=SCOPES, redirect_uri=redirect_uri)
    url, state = flow.authorization_url(access_type="offline", prompt="consent", include_granted_scopes="false")
    await db.oauth_states.insert_one({
        "state": state,
        "user_id": user_id,
        "redirect_uri": redirect_uri,
        "origin": frontend_origin,
        "code_verifier": flow.code_verifier if isinstance(getattr(flow, "code_verifier", None), str) else None,
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
    })
    return url


async def handle_callback(code: str, state: str) -> str:
    import warnings

    from google_auth_oauthlib.flow import Flow
    from fastapi import HTTPException

    doc = await db.oauth_states.find_one({"state": state})
    if not doc or parse_iso(doc.get("expires_at")) is None or parse_iso(doc["expires_at"]) < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")
    user_id = doc["user_id"]
    client_id, client_secret = await get_google_config(user_id)
    flow = Flow.from_client_config(_client_config(client_id, client_secret), scopes=SCOPES,
                                   redirect_uri=doc["redirect_uri"])
    if doc.get("code_verifier"):
        flow.code_verifier = doc["code_verifier"]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        flow.fetch_token(code=code)
    creds = flow.credentials
    service = build_service(creds)
    profile = await asyncio.to_thread(lambda: service.users().getProfile(userId="me").execute())
    expires_at = creds.expiry.isoformat() if creds.expiry else (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    await db.gmail_connections.update_one(
        {"user_id": user_id},
        {"$set": {
            "email": profile.get("emailAddress", ""),
            "access_token": encrypt(creds.token or ""),
            "refresh_token": encrypt(creds.refresh_token) if creds.refresh_token else None,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "expires_at": expires_at,
            "scopes": list(creds.scopes or SCOPES),
            "connected_at": utc_now_iso(),
            "status": "connected",
        }},
        upsert=True,
    )
    await db.oauth_states.delete_one({"state": state})
    return doc.get("origin") or "/"


def build_service(creds):
    from googleapiclient.discovery import build

    return build("gmail", "v1", credentials=creds, cache_discovery=False)


async def get_creds(user_id: str):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google.auth.exceptions import RefreshError

    conn = await db.gmail_connections.find_one({"user_id": user_id}, {"_id": 0})
    if not conn:
        return None
    if conn.get("status") == "reauth_required":
        return None

    cfg_client_id, cfg_client_secret = await get_google_config(user_id)
    client_id = conn.get("client_id") or cfg_client_id
    client_secret = cfg_client_secret

    creds = Credentials(
        token=decrypt(conn.get("access_token", "")),
        refresh_token=decrypt(conn["refresh_token"]) if conn.get("refresh_token") else None,
        token_uri=conn.get("token_uri") or "https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=conn.get("scopes", SCOPES),
    )
    expires = parse_iso(conn.get("expires_at"))
    if expires and expires <= datetime.now(timezone.utc) and creds.refresh_token:
        try:
            await asyncio.to_thread(creds.refresh, Request())
            await db.gmail_connections.update_one(
                {"user_id": user_id},
                {"$set": {
                    "access_token": encrypt(creds.token),
                    "expires_at": (creds.expiry or datetime.now(timezone.utc)).isoformat(),
                    "status": "connected",
                    "last_refresh_error": None,
                }},
            )
        except RefreshError as exc:
            logger.error("Gmail token refresh rejected for user %s: %s", user_id, exc)
            await db.gmail_connections.update_one(
                {"user_id": user_id},
                {"$set": {"status": "reauth_required", "last_refresh_error": str(exc)[:200]}},
            )
            return None
        except Exception as exc:
            if "invalid_grant" in str(exc).lower():
                logger.error("Gmail token refresh rejected (invalid_grant) for user %s: %s", user_id, exc)
                await db.gmail_connections.update_one(
                    {"user_id": user_id},
                    {"$set": {"status": "reauth_required", "last_refresh_error": str(exc)[:200]}},
                )
                return None
            logger.warning("Temporary error refreshing Gmail token for user %s: %s", user_id, exc)
            return None
    return creds


async def send_gmail_email(user_id: str, to: str, subject: str, body_text: str,
                           attachment_bytes: bytes | None = None, attachment_filename: str | None = None,
                           reply_to: str | None = None, html_body: str | None = None) -> tuple[str, str | None]:
    creds = await get_creds(user_id)
    if not creds:
        raise RuntimeError("Gmail not connected")

    def _send() -> dict:
        msg = MIMEMultipart("mixed")
        msg["to"] = to
        msg["subject"] = subject
        if reply_to:
            msg["reply-to"] = reply_to

        alt_part = MIMEMultipart("alternative")
        alt_part.attach(MIMEText(body_text or "", "plain"))
        if html_body:
            alt_part.attach(MIMEText(html_body, "html"))
        msg.attach(alt_part)

        if attachment_bytes:
            part = MIMEApplication(attachment_bytes, _subtype="pdf")
            part.add_header("Content-Disposition", "attachment", filename=attachment_filename or "resume.pdf")
            msg.attach(part)
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        service = build_service(creds)
        return service.users().messages().send(userId="me", body={"raw": raw}).execute()

    try:
        result = await asyncio.to_thread(_send)
        return result.get("id", ""), result.get("threadId")
    except Exception as exc:
        detail = getattr(exc, "resp", None)
        reason = getattr(detail, "status", "") or ""
        logger.error("Gmail send failed: %s %s", reason, str(exc)[:300])
        raise RuntimeError(f"Gmail send failed: {str(exc)[:200]}")


async def list_recent_inbox(user_id: str, days: int = 14, max_results: int = 30) -> list[dict]:
    creds = await get_creds(user_id)
    if not creds:
        return []
    service = build_service(creds)

    def _list() -> list[dict]:
        res = service.users().messages().list(
            userId="me", q=f"in:inbox newer_than:{days}d", maxResults=max_results).execute()
        out = []
        for m in res.get("messages", []) or []:
            meta = service.users().messages().get(
                userId="me", id=m["id"], format="metadata",
                metadataHeaders=["From", "Subject", "Date"]).execute()
            headers = {h["name"].lower(): h["value"] for h in meta.get("payload", {}).get("headers", [])}
            out.append({
                "id": m["id"],
                "thread_id": meta.get("threadId"),
                "from": headers.get("from", ""),
                "subject": headers.get("subject", ""),
                "date": headers.get("date", ""),
                "snippet": meta.get("snippet", ""),
            })
        return out

    try:
        return await asyncio.to_thread(_list)
    except Exception as exc:
        logger.error("Gmail inbox scan failed: %s", str(exc)[:200])
        return []


async def get_message_text(user_id: str, msg_id: str) -> str:
    creds = await get_creds(user_id)
    if not creds:
        return ""
    service = build_service(creds)

    def _get() -> str:
        msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
        parts = []

        def walk(payload):
            mime = payload.get("mimeType", "")
            if mime == "text/plain" and payload.get("body", {}).get("data"):
                parts.append(base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", "ignore"))
            for p in payload.get("parts", []) or []:
                walk(p)

        walk(msg.get("payload", {}))
        if not parts:
            snippet = msg.get("snippet", "")
            return snippet
        return "\n".join(parts)

    try:
        return await asyncio.to_thread(_get)
    except Exception as exc:
        logger.error("Gmail message fetch failed: %s", str(exc)[:200])
        return ""
