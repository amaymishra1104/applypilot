import hashlib
from fastapi import HTTPException, Request

from db import db, utc_now_iso
from auth import (
    COOKIE_NAME,
    OWNER_USER_ID,
    get_owner_email,
    verify_session_token,
)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def get_current_user(request: Request) -> dict:
    """Dependency for authenticated routes: reads the session cookie,
    Bearer token header, or X-ApplyPilot-Token header.
    Returns the user document (stable user_id='owner' for single-user auth)."""
    # 1. Extension token support via header
    ext_token = request.headers.get("x-applypilot-token", "").strip()
    if ext_token:
        doc = await db.extension_tokens.find_one(
            {"token_hash": _token_hash(ext_token), "revoked": {"$ne": True}},
            {"_id": 0},
        )
        if not doc:
            raise HTTPException(status_code=401, detail="Browser helper token is invalid or revoked")
        await db.extension_tokens.update_one(
            {"token_hash": doc["token_hash"]},
            {"$set": {"last_used_at": utc_now_iso()}},
        )
        user = await db.users.find_one({"user_id": doc["user_id"]}, {"_id": 0})
        if user:
            return user
        return {"user_id": doc["user_id"], "email": get_owner_email(), "name": "Owner"}

    # 2. Session cookie or Authorization: Bearer
    token = request.cookies.get(COOKIE_NAME, "")
    if not token:
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()

    if not token:
        raise HTTPException(status_code=401, detail="Not signed in")

    claims = verify_session_token(token)
    uid = claims.get("sub", OWNER_USER_ID)
    owner_email = claims.get("email") or get_owner_email()

    user = await db.users.find_one({"user_id": uid}, {"_id": 0})
    if not user:
        user = {
            "user_id": uid,
            "email": owner_email,
            "name": "Owner",
            "created_at": utc_now_iso(),
        }
        await db.users.update_one({"user_id": uid}, {"$set": user}, upsert=True)
    return user


async def get_owned(collection: str, doc_id: str, user_id: str) -> dict:
    """Fetch a record scoped to its owner; not-found and not-yours are the same 404."""
    doc = await db[collection].find_one({"id": doc_id, "user_id": user_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    return doc
