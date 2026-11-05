import os

import requests as http
from fastapi import Depends, HTTPException
from pymongo.errors import DuplicateKeyError

from clerk_auth import require_user
from db import db, utc_now_iso


async def get_current_user(user: dict = Depends(require_user)) -> dict:
    """Return the app-level user doc, creating it (with Clerk email) on first sign-in."""
    uid = user["user_id"]
    doc = await db.users.find_one({"user_id": uid}, {"_id": 0})
    if doc is None:
        email, name = "", ""
        sk = os.environ.get("CLERK_SECRET_KEY")
        if sk:
            try:
                r = http.get(
                    f"https://api.clerk.com/v1/users/{uid}", timeout=10,
                    headers={"Authorization": f"Bearer {sk}", "User-Agent": "emergent-app"},
                )
                if r.ok:
                    u = r.json()
                    primary = u.get("primary_email_address_id")
                    email = next((e["email_address"] for e in u.get("email_addresses", [])
                                  if e.get("id") == primary and e.get("verification", {}).get("status") == "verified"),
                                 "")
                    if not email:
                        email = next((e["email_address"] for e in u.get("email_addresses", [])), "")
                    name = " ".join(filter(None, [u.get("first_name"), u.get("last_name")])).strip()
            except Exception:
                pass
        new_doc = {"user_id": uid, "email": email, "name": name, "created_at": utc_now_iso()}
        try:
            await db.users.insert_one(new_doc.copy())
        except DuplicateKeyError:
            pass  # a parallel first request inserted it; re-read below
        doc = await db.users.find_one({"user_id": uid}, {"_id": 0})
    return doc


async def get_owned(collection: str, doc_id: str, user_id: str) -> dict:
    """Fetch a record scoped to its owner; not-found and not-yours are the same 404."""
    doc = await db[collection].find_one({"id": doc_id, "user_id": user_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    return doc
