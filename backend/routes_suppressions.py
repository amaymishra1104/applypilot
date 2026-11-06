from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from application_engine import is_email_suppressed, suppress_email, unsuppress_email, email_is_valid, normalize
from db import db
from deps import get_current_user

router = APIRouter(prefix="/api", tags=["suppressions"])


class SuppressionIn(BaseModel):
    email: str = Field(..., min_length=3)
    reason: Optional[str] = "manual"


@router.get("/suppressions")
async def list_suppressions(user: dict = Depends(get_current_user)):
    uid = user["user_id"]
    cursor = db.suppressions.find({"user_id": uid}, {"_id": 0}).sort("created_at", -1)
    return await cursor.to_list(1000)


@router.post("/suppressions")
async def add_suppression(body: SuppressionIn, user: dict = Depends(get_current_user)):
    uid = user["user_id"]
    clean_email = normalize(body.email)
    if not email_is_valid(clean_email):
        raise HTTPException(status_code=400, detail="Invalid email address")
    doc = await suppress_email(uid, clean_email, reason=body.reason or "manual", source="user")
    return doc


@router.delete("/suppressions/{email}")
async def remove_suppression(email: str, user: dict = Depends(get_current_user)):
    uid = user["user_id"]
    clean_email = normalize(email)
    deleted = await unsuppress_email(uid, clean_email)
    if not deleted:
        raise HTTPException(status_code=404, detail="Email not found in suppression list")
    return {"ok": True, "email": clean_email}
