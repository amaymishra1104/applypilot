import csv
import io
import re
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from db import db, utc_now_iso
from deps import get_current_user, get_owned

router = APIRouter(prefix="/api", tags=["contacts"])

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

FIELDS = ["company_name", "hr_name", "hr_email", "company_website", "job_role",
          "job_description", "application_source", "notes"]

HEADER_ALIASES = {
    "company": "company_name", "company_name": "company_name", "companyname": "company_name",
    "hr_name": "hr_name", "name": "hr_name", "recruiter_name": "hr_name", "hrname": "hr_name",
    "hr_email": "hr_email", "email": "hr_email", "email_address": "hr_email", "hremail": "hr_email",
    "company_website": "company_website", "website": "company_website", "url": "company_website",
    "job_role": "job_role", "role": "job_role", "position": "job_role",
    "job_description": "job_description", "description": "job_description",
    "application_source": "application_source", "source": "application_source",
    "notes": "notes", "note": "notes",
}


class ContactIn(BaseModel):
    company_name: str = ""
    hr_name: str = ""
    hr_email: str
    company_website: str = ""
    job_role: str = ""
    job_description: str = ""
    application_source: str = ""
    notes: str = ""


def norm_email(email: str) -> str:
    return (email or "").strip().lower()


async def find_duplicate(user_id: str, email: str) -> Optional[dict]:
    return await db.hr_contacts.find_one(
        {"user_id": user_id, "hr_email_norm": norm_email(email)}, {"_id": 0})


def build_doc(user_id: str, data: dict) -> dict:
    doc = {"id": uuid.uuid4().hex, "user_id": user_id}
    for field in FIELDS:
        value = data.get(field) or ""
        doc[field] = str(value).strip()[:4000]
    doc["hr_email"] = norm_email(doc["hr_email"])
    doc["hr_email_norm"] = doc["hr_email"]
    doc["created_at"] = utc_now_iso()
    return doc


@router.get("/contacts")
async def list_contacts(search: str = "", user: dict = Depends(get_current_user)):
    query = {"user_id": user["user_id"]}
    if search.strip():
        rx = {"$regex": re.escape(search.strip()), "$options": "i"}
        query["$or"] = [{"company_name": rx}, {"hr_name": rx}, {"hr_email": rx}, {"job_role": rx}]
    contacts = await db.hr_contacts.find(query, {"_id": 0}).sort("created_at", -1).to_list(1000)
    return contacts


@router.post("/contacts")
async def create_contact(body: ContactIn, user: dict = Depends(get_current_user)):
    if not EMAIL_RE.match(norm_email(body.hr_email)):
        raise HTTPException(status_code=400, detail="Invalid email address")
    if await find_duplicate(user["user_id"], body.hr_email):
        raise HTTPException(status_code=409, detail="A contact with this email already exists")
    doc = build_doc(user["user_id"], body.model_dump())
    await db.hr_contacts.insert_one(doc.copy())
    return doc


@router.put("/contacts/{contact_id}")
async def update_contact(contact_id: str, body: ContactIn, user: dict = Depends(get_current_user)):
    await get_owned("hr_contacts", contact_id, user["user_id"])
    if not EMAIL_RE.match(norm_email(body.hr_email)):
        raise HTTPException(status_code=400, detail="Invalid email address")
    dup = await find_duplicate(user["user_id"], body.hr_email)
    if dup and dup["id"] != contact_id:
        raise HTTPException(status_code=409, detail="A contact with this email already exists")
    doc = build_doc(user["user_id"], body.model_dump())
    doc["id"] = contact_id
    await db.hr_contacts.replace_one({"id": contact_id, "user_id": user["user_id"]}, doc)
    return doc


@router.delete("/contacts/{contact_id}")
async def delete_contact(contact_id: str, user: dict = Depends(get_current_user)):
    await get_owned("hr_contacts", contact_id, user["user_id"])
    await db.hr_contacts.delete_one({"id": contact_id, "user_id": user["user_id"]})
    return {"ok": True}


def _normalize_headers(rows: list[dict]) -> list[dict]:
    mapped = []
    for row in rows:
        item = {}
        for key, value in row.items():
            clean = re.sub(r"[\s\-]+", "_", str(key or "").strip().lower())
            field = HEADER_ALIASES.get(clean) or (clean if clean in FIELDS else None)
            if field:
                item[field] = value
        mapped.append(item)
    return mapped


def _read_spreadsheet(filename: str, data: bytes) -> list[dict]:
    name = (filename or "").lower()
    if name.endswith(".xlsx") or name.endswith(".xls"):
        try:
            from openpyxl import load_workbook

            wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            ws = wb.active
            rows = list(ws.iter_rows(values_only=True))
            if not rows:
                return []
            headers = [str(h) if h is not None else "" for h in rows[0]]
            return [dict(zip(headers, r)) for r in rows[1:] if any(v is not None for v in r)]
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Could not read Excel file: {exc}")
    try:
        text = data.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        return list(reader)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not read CSV file: {exc}")


@router.post("/contacts/import")
async def import_contacts(file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    data = await file.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 5 MB)")
    rows = _normalize_headers(_read_spreadsheet(file.filename, data))
    result = {"imported": 0, "duplicates": [], "errors": []}
    seen_in_file = set()
    for index, row in enumerate(rows, start=2):
        email = norm_email(str(row.get("hr_email") or ""))
        if not email:
            result["errors"].append({"row": index, "reason": "Missing HR email"})
            continue
        if not EMAIL_RE.match(email):
            result["errors"].append({"row": index, "reason": f"Invalid email: {email}"})
            continue
        if email in seen_in_file:
            result["duplicates"].append({"row": index, "reason": f"Duplicate in file: {email}"})
            continue
        if await find_duplicate(user["user_id"], email):
            result["duplicates"].append({"row": index, "reason": f"Already exists: {email}"})
            continue
        seen_in_file.add(email)
        await db.hr_contacts.insert_one(build_doc(user["user_id"], row).copy())
        result["imported"] += 1
    return result
