import io
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from db import db, utc_now_iso
from deps import get_current_user, get_owned
from storage import get_object, put_object, object_exists

router = APIRouter(prefix="/api", tags=["roles"])

MAX_PDF_BYTES = 5 * 1024 * 1024


class RoleIn(BaseModel):
    title: str
    description: str = ""
    skills: List[str] = []
    experience_required: str = ""
    notes: str = ""


def clean_version(v: dict) -> dict:
    res = {k: val for k, val in v.items() if k not in ("resume_text",)}
    storage_path = v.get("storage_path") or ""
    if not storage_path or not object_exists(storage_path):
        res["reupload_required"] = True
        res["reupload_warning"] = "Resume file missing from storage; re-upload required"
    return res


def extract_pdf_text(data: bytes) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        text = "\n".join((page.extract_text() or "") for page in reader.pages[:15])
        return text[:15000].strip()
    except Exception:
        return ""


async def role_payload(user_id: str, profile: dict) -> dict:
    versions = await db.resume_versions.find(
        {"user_id": user_id, "role_profile_id": profile["id"], "is_deleted": {"$ne": True}}, {"_id": 0},
    ).sort("version_no", -1).to_list(100)
    active = next((clean_version(v) for v in versions if v.get("active")), None)
    skills = profile.get("skills") or profile.get("target_keywords") or []
    payload = {**profile, "skills": skills, "active_resume": active, "version_count": len(versions)}
    if active and active.get("reupload_required"):
        payload["reupload_required"] = True
        payload["reupload_warning"] = "Active resume file is missing from storage; re-upload required"
    return payload


@router.get("/roles")
async def list_roles(user: dict = Depends(get_current_user)):
    profiles = await db.role_profiles.find({"user_id": user["user_id"]}, {"_id": 0}).sort("created_at", -1).to_list(500)
    return [await role_payload(user["user_id"], p) for p in profiles]


@router.post("/roles")
async def create_role(body: RoleIn, user: dict = Depends(get_current_user)):
    if not body.title.strip():
        raise HTTPException(status_code=400, detail="Role title is required")
    doc = {
        "id": uuid.uuid4().hex,
        "user_id": user["user_id"],
        "title": body.title.strip(),
        "description": body.description.strip(),
        "skills": [s.strip() for s in body.skills if s.strip()],
        "experience_required": body.experience_required.strip(),
        "notes": body.notes.strip(),
        "created_at": utc_now_iso(),
        "updated_at": utc_now_iso(),
    }
    await db.role_profiles.insert_one(doc.copy())
    return await role_payload(user["user_id"], doc)


@router.get("/roles/{role_id}")
async def get_role(role_id: str, user: dict = Depends(get_current_user)):
    profile = await get_owned("role_profiles", role_id, user["user_id"])
    return await role_payload(user["user_id"], profile)


@router.put("/roles/{role_id}")
async def update_role(role_id: str, body: RoleIn, user: dict = Depends(get_current_user)):
    await get_owned("role_profiles", role_id, user["user_id"])
    await db.role_profiles.update_one(
        {"id": role_id, "user_id": user["user_id"]},
        {"$set": {"title": body.title.strip(), "description": body.description.strip(),
                  "skills": [s.strip() for s in body.skills if s.strip()],
                  "experience_required": body.experience_required.strip(),
                  "notes": body.notes.strip(), "updated_at": utc_now_iso()}})
    profile = await db.role_profiles.find_one({"id": role_id, "user_id": user["user_id"]}, {"_id": 0})
    return await role_payload(user["user_id"], profile)


@router.delete("/roles/{role_id}")
async def delete_role(role_id: str, user: dict = Depends(get_current_user)):
    await get_owned("role_profiles", role_id, user["user_id"])
    await db.role_profiles.delete_one({"id": role_id, "user_id": user["user_id"]})
    await db.resume_versions.update_many(
        {"user_id": user["user_id"], "role_profile_id": role_id},
        {"$set": {"is_deleted": True}})
    return {"ok": True}


@router.post("/roles/{role_id}/resumes")
async def upload_resume(role_id: str, file: UploadFile = File(...), name: str = Form(""),
                        user: dict = Depends(get_current_user)):
    await get_owned("role_profiles", role_id, user["user_id"])
    data = await file.read()
    if len(data) == 0:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(data) > MAX_PDF_BYTES:
        raise HTTPException(status_code=400, detail="PDF must be 5 MB or smaller")
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")
    storage_path = f"applypilot/resumes/{user['user_id']}/{uuid.uuid4()}.pdf"
    try:
        result = put_object(storage_path, data, "application/pdf")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"File storage failed: {exc}")
    storage_path = result.get("path", storage_path)
    count = await db.resume_versions.count_documents(
        {"user_id": user["user_id"], "role_profile_id": role_id, "is_deleted": {"$ne": True}})
    extracted = extract_pdf_text(data)
    warning = None
    if len(extracted) < 300:
        warning = ("The uploaded PDF yielded very little text (< 300 characters). "
                   "It may be scanned or image-based, which will produce poor AI matches.")

    version = {
        "id": uuid.uuid4().hex,
        "user_id": user["user_id"],
        "role_profile_id": role_id,
        "version_no": count + 1,
        "name": (name or file.filename.rsplit(".", 1)[0]).strip()[:120],
        "filename": file.filename,
        "size": len(data),
        "storage_path": storage_path,
        "content_type": "application/pdf",
        "active": True,
        "resume_text": extracted,
        "is_deleted": False,
        "created_at": utc_now_iso(),
    }
    await db.resume_versions.update_many(
        {"user_id": user["user_id"], "role_profile_id": role_id}, {"$set": {"active": False}})
    await db.resume_versions.insert_one(version.copy())
    profile = await db.role_profiles.find_one({"id": role_id, "user_id": user["user_id"]}, {"_id": 0})
    payload = await role_payload(user["user_id"], profile)
    if warning:
        payload["warning"] = warning
    return payload


@router.get("/roles/{role_id}/resumes")
async def list_versions(role_id: str, user: dict = Depends(get_current_user)):
    await get_owned("role_profiles", role_id, user["user_id"])
    versions = await db.resume_versions.find(
        {"user_id": user["user_id"], "role_profile_id": role_id, "is_deleted": {"$ne": True}}, {"_id": 0},
    ).sort("version_no", -1).to_list(100)
    return [clean_version(v) for v in versions]


@router.put("/roles/{role_id}/resumes/{version_id}/activate")
async def activate_version(role_id: str, version_id: str, user: dict = Depends(get_current_user)):
    await get_owned("role_profiles", role_id, user["user_id"])
    version = await db.resume_versions.find_one(
        {"id": version_id, "user_id": user["user_id"], "role_profile_id": role_id,
         "is_deleted": {"$ne": True}}, {"_id": 0})
    if not version:
        raise HTTPException(status_code=404, detail="Resume version not found")
    await db.resume_versions.update_many(
        {"user_id": user["user_id"], "role_profile_id": role_id}, {"$set": {"active": False}})
    await db.resume_versions.update_one({"id": version_id}, {"$set": {"active": True}})
    return {"ok": True}


@router.delete("/roles/{role_id}/resumes/{version_id}")
async def delete_version(role_id: str, version_id: str, user: dict = Depends(get_current_user)):
    await get_owned("role_profiles", role_id, user["user_id"])
    version = await db.resume_versions.find_one({"id": version_id, "user_id": user["user_id"]}, {"_id": 0})
    if not version:
        raise HTTPException(status_code=404, detail="Resume version not found")
    await db.resume_versions.update_one({"id": version_id}, {"$set": {"is_deleted": True, "active": False}})
    if version.get("active"):
        latest = await db.resume_versions.find_one(
            {"user_id": user["user_id"], "role_profile_id": role_id, "is_deleted": {"$ne": True}},
            {"_id": 0}, sort=[("version_no", -1)])
        if latest:
            await db.resume_versions.update_one({"id": latest["id"]}, {"$set": {"active": True}})
    return {"ok": True}


async def _serve_version(version_id: str, uid: str, inline: bool):
    version = await db.resume_versions.find_one(
        {"id": version_id, "user_id": uid, "is_deleted": {"$ne": True}}, {"_id": 0})
    if not version:
        raise HTTPException(status_code=404, detail="Resume version not found")
    try:
        data, _ = get_object(version["storage_path"])
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found; re-upload required")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not load file: {exc}")
    disposition = "inline" if inline else "attachment"
    filename = version.get("filename") or f"resume-v{version['version_no']}.pdf"
    return Response(
        content=data, media_type="application/pdf",
        headers={"Content-Disposition": f'{disposition}; filename="{filename}"'})


@router.get("/resumes/{version_id}/download")
async def download_resume(version_id: str, user: dict = Depends(get_current_user)):
    return await _serve_version(version_id, user["user_id"], inline=False)


@router.get("/resumes/{version_id}/preview")
async def preview_resume(version_id: str, user: dict = Depends(get_current_user)):
    return await _serve_version(version_id, user["user_id"], inline=True)
