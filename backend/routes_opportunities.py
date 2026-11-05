import re
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

import ai_service
import gmail_service
from db import db, utc_now_iso
from deps import get_current_user, get_owned
from application_engine import add_event

router = APIRouter(prefix="/api", tags=["opportunities"])


class OpportunityIn(BaseModel):
    company_name: str = ""
    job_title: str = ""
    job_description: str = ""
    required_skills: List[str] = []
    experience_required: str = ""
    source: str = "manual"
    hr_contact_id: Optional[str] = None


class MatchConfirmIn(BaseModel):
    role_profile_id: Optional[str] = None
    resume_version_id: Optional[str] = None


def build_doc(user_id: str, data: dict, extra: dict | None = None) -> dict:
    doc = {
        "id": uuid.uuid4().hex,
        "user_id": user_id,
        "company_name": (data.get("company_name") or "").strip()[:200],
        "job_title": (data.get("job_title") or "").strip()[:200],
        "job_title_norm": re.sub(r"\s+", " ", (data.get("job_title") or "").strip().lower()),
        "job_description": (data.get("job_description") or "").strip()[:20000],
        "required_skills": [s.strip() for s in (data.get("required_skills") or []) if str(s).strip()][:30],
        "experience_required": (data.get("experience_required") or "").strip()[:200],
        "source": data.get("source") or "manual",
        "hr_contact_id": data.get("hr_contact_id") or None,
        "status": "new",
        "created_at": utc_now_iso(),
    }
    if extra:
        doc.update(extra)
    return doc


@router.get("/opportunities")
async def list_opportunities(user: dict = Depends(get_current_user)):
    docs = await db.job_opportunities.find({"user_id": user["user_id"]}, {"_id": 0}).sort("created_at", -1).to_list(200)
    matches = await db.job_matches.find({"user_id": user["user_id"]}, {"_id": 0}).to_list(500)
    by_opp = {}
    for m in matches:
        by_opp.setdefault(m["opportunity_id"], m)
    for doc in docs:
        doc["match"] = by_opp.get(doc["id"])
    return docs


@router.post("/opportunities")
async def create_opportunity(body: OpportunityIn, user: dict = Depends(get_current_user)):
    if not body.job_title.strip() and not body.job_description.strip():
        raise HTTPException(status_code=400, detail="Job title or description is required")
    doc = build_doc(user["user_id"], body.model_dump())
    await db.job_opportunities.insert_one(doc.copy())
    await add_event(user["user_id"], None, "opportunity_added", f"Job opportunity added: {doc['job_title']}")
    return doc


@router.post("/opportunities/parse")
async def parse_opportunity(body: dict, user: dict = Depends(get_current_user)):
    raw = (body or {}).get("text", "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Paste the job description text")
    settings = await db.app_settings.find_one({"user_id": user["user_id"]}, {"_id": 0}) or {}
    parsed = await ai_service.parse_job_description(raw, settings.get("ai_model"))
    if not parsed:
        raise HTTPException(status_code=502, detail="AI could not parse this job description - try editing it manually")
    return parsed


@router.post("/opportunities/import")
async def import_opportunities(file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    import routes_contacts as contacts_routes

    data = await file.read()
    rows = contacts_routes._read_spreadsheet(file.filename, data)
    created = []
    for row in rows:
        title = str(row.get("job_title") or row.get("job_role") or row.get("role") or "").strip()
        if not title:
            continue
        doc = build_doc(user["user_id"], {
            "company_name": str(row.get("company_name") or row.get("company") or ""),
            "job_title": title,
            "job_description": str(row.get("job_description") or row.get("description") or ""),
            "required_skills": [],
            "source": "csv_import",
        })
        await db.job_opportunities.insert_one(doc.copy())
        created.append(doc)
    return {"imported": len(created), "opportunities": created}


@router.get("/opportunities/{opp_id}")
async def get_opportunity(opp_id: str, user: dict = Depends(get_current_user)):
    opp = await get_owned("job_opportunities", opp_id, user["user_id"])
    match = await db.job_matches.find_one({"user_id": user["user_id"], "opportunity_id": opp_id}, {"_id": 0})
    company = None
    if opp.get("company_name"):
        company = await db.companies.find_one(
            {"user_id": user["user_id"], "name": opp["company_name"].strip()}, {"_id": 0})
    return {**opp, "match": match, "company": company}


@router.put("/opportunities/{opp_id}")
async def update_opportunity(opp_id: str, body: OpportunityIn, user: dict = Depends(get_current_user)):
    await get_owned("job_opportunities", opp_id, user["user_id"])
    doc = build_doc(user["user_id"], body.model_dump())
    doc["id"] = opp_id
    await db.job_opportunities.replace_one({"id": opp_id, "user_id": user["user_id"]}, doc)
    return doc


@router.delete("/opportunities/{opp_id}")
async def delete_opportunity(opp_id: str, user: dict = Depends(get_current_user)):
    await get_owned("job_opportunities", opp_id, user["user_id"])
    await db.job_opportunities.delete_one({"id": opp_id, "user_id": user["user_id"]})
    await db.job_matches.delete_many({"user_id": user["user_id"], "opportunity_id": opp_id})
    return {"ok": True}


async def _profiles_with_resumes(user_id: str) -> list[dict]:
    profiles = await db.role_profiles.find({"user_id": user_id}, {"_id": 0}).to_list(200)
    if not profiles:
        return []
    versions = await db.resume_versions.find(
        {"user_id": user_id, "is_deleted": {"$ne": True}, "active": True}, {"_id": 0}).to_list(300)
    by_role = {v["role_profile_id"]: v for v in versions}
    return [{**p, "resume_text": (by_role.get(p["id"]) or {}).get("resume_text", "")} for p in profiles]


@router.post("/opportunities/{opp_id}/match")
async def run_match(opp_id: str, user: dict = Depends(get_current_user)):
    opp = await get_owned("job_opportunities", opp_id, user["user_id"])
    profiles = await _profiles_with_resumes(user["user_id"])
    if not profiles:
        raise HTTPException(status_code=400, detail="no_role_profiles")
    settings = await db.app_settings.find_one({"user_id": user["user_id"]}, {"_id": 0}) or {}
    job = {
        "company_name": opp.get("company_name"),
        "job_title": opp.get("job_title"),
        "required_skills": opp.get("required_skills", []),
        "experience_required": opp.get("experience_required", ""),
        "description_summary": None,
        "job_description": opp.get("job_description", ""),
    }
    result = await ai_service.match_opportunity(job, profiles, settings.get("ai_model"))
    if not result or not result.get("role_profile_id"):
        raise HTTPException(status_code=502, detail="AI could not determine a matching role profile")
    valid_ids = {p["id"] for p in profiles}
    if result["role_profile_id"] not in valid_ids:
        raise HTTPException(status_code=502, detail="AI returned an invalid profile")
    matched_profile = next(p for p in profiles if p["id"] == result["role_profile_id"])
    versions = await db.resume_versions.find(
        {"user_id": user["user_id"], "role_profile_id": matched_profile["id"], "is_deleted": {"$ne": True}},
        {"_id": 0}).sort("version_no", -1).to_list(50)
    active_version = next((v for v in versions if v.get("active")), versions[0] if versions else None)
    alternatives = [a for a in result.get("alternatives", []) if a.get("id") in valid_ids
                    and a["id"] != result["role_profile_id"]]
    match = {
        "id": uuid.uuid4().hex,
        "user_id": user["user_id"],
        "opportunity_id": opp_id,
        "role_profile_id": matched_profile["id"],
        "role_profile_title": matched_profile["title"],
        "resume_version_id": active_version["id"] if active_version else None,
        "resume_version_no": active_version["version_no"] if active_version else None,
        "resume_name": active_version["name"] if active_version else None,
        "score": int(result.get("score", 0)),
        "confidence": result.get("confidence", "low"),
        "matched_skills": result.get("matched_skills", []),
        "missing_skills": result.get("missing_skills", []),
        "reasoning": result.get("reasoning", ""),
        "alternatives": alternatives[:2],
        "confirmed": False,
        "overridden": False,
        "created_at": utc_now_iso(),
    }
    if active_version and active_version.get("resume_text"):
        ats = await ai_service.ats_analyze(active_version["resume_text"], job, settings.get("ai_model"))
        match["ats"] = ats
    await db.job_matches.delete_many({"user_id": user["user_id"], "opportunity_id": opp_id})
    await db.job_matches.insert_one(match.copy())
    await db.job_opportunities.update_one({"id": opp_id, "user_id": user["user_id"]},
                                          {"$set": {"status": "matched"}})
    return match


@router.post("/opportunities/{opp_id}/match/confirm")
async def confirm_match(opp_id: str, body: MatchConfirmIn, user: dict = Depends(get_current_user)):
    await get_owned("job_opportunities", opp_id, user["user_id"])
    match = await db.job_matches.find_one({"user_id": user["user_id"], "opportunity_id": opp_id}, {"_id": 0})
    if not match:
        raise HTTPException(status_code=404, detail="Run the AI match first")
    updates = {"confirmed": True}
    if body.role_profile_id and body.role_profile_id != match["role_profile_id"]:
        profile = await get_owned("role_profiles", body.role_profile_id, user["user_id"])
        updates["role_profile_id"] = profile["id"]
        updates["role_profile_title"] = profile["title"]
        versions = await db.resume_versions.find(
            {"user_id": user["user_id"], "role_profile_id": profile["id"], "is_deleted": {"$ne": True}},
            {"_id": 0}).sort("version_no", -1).to_list(50)
        active_version = next((v for v in versions if v.get("active")), versions[0] if versions else None)
        updates["resume_version_id"] = active_version["id"] if active_version else None
        updates["resume_version_no"] = active_version["version_no"] if active_version else None
        updates["resume_name"] = active_version["name"] if active_version else None
        updates["overridden"] = True
    if body.resume_version_id:
        version = await db.resume_versions.find_one(
            {"id": body.resume_version_id, "user_id": user["user_id"], "is_deleted": {"$ne": True}}, {"_id": 0})
        if not version:
            raise HTTPException(status_code=404, detail="Resume version not found")
        updates["resume_version_id"] = version["id"]
        updates["resume_version_no"] = version["version_no"]
        updates["resume_name"] = version["name"]
        if version["role_profile_id"] != updates.get("role_profile_id", match["role_profile_id"]):
            raise HTTPException(status_code=400, detail="Resume does not belong to the selected role profile")
        updates["overridden"] = True
    await db.job_matches.update_one({"id": match["id"]}, {"$set": updates})
    return await db.job_matches.find_one({"id": match["id"]}, {"_id": 0})


@router.post("/opportunities/{opp_id}/research")
async def research_company(opp_id: str, user: dict = Depends(get_current_user)):
    opp = await get_owned("job_opportunities", opp_id, user["user_id"])
    name = (opp.get("company_name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Company name is missing - add it first")
    settings = await db.app_settings.find_one({"user_id": user["user_id"]}, {"_id": 0}) or {}
    research = await ai_service.research_company(name, settings.get("ai_model"))
    if not research:
        raise HTTPException(status_code=502, detail="AI research failed - try again")
    await db.companies.update_one(
        {"user_id": user["user_id"], "name": name},
        {"$set": {"background": research.get("background", ""), "known_for": research.get("known_for", []),
                  "confidence": research.get("confidence", "low"), "caveat": research.get("caveat", ""),
                  "researched_at": utc_now_iso()}},
        upsert=True)
    return research


@router.post("/opportunities/scan-inbox")
async def scan_inbox(user: dict = Depends(get_current_user)):
    conn = await db.gmail_connections.find_one({"user_id": user["user_id"]}, {"_id": 0})
    if not conn:
        raise HTTPException(status_code=400, detail="Connect your Gmail account first")
    messages = await gmail_service.list_recent_inbox(user["user_id"], days=21, max_results=40)
    if not messages:
        return {"created": [], "scanned": 0}
    settings = await db.app_settings.find_one({"user_id": user["user_id"]}, {"_id": 0}) or {}
    found = await ai_service.extract_opportunities_from_emails(
        [{"from": m.get("from"), "subject": m.get("subject"), "snippet": m.get("snippet")} for m in messages],
        settings.get("ai_model"))
    created = []
    existing = {re.sub(r"\s+", " ", (o["company_name"] + "|" + o["job_title"]).lower())
                for o in await db.job_opportunities.find({"user_id": user["user_id"]}, {"_id": 0}).to_list(500)}
    for item in found:
        key = re.sub(r"\s+", " ", ((item.get("company_name") or "") + "|" + (item.get("job_title") or "")).lower())
        if not item.get("job_title") or key in existing:
            continue
        existing.add(key)
        doc = build_doc(user["user_id"], {
            "company_name": item.get("company_name", ""),
            "job_title": item["job_title"],
            "job_description": item.get("description_summary", ""),
            "required_skills": item.get("required_skills", []),
            "source": "gmail_inbox",
        }, extra={"status": "from_inbox", "from_email": item.get("from_email", ""),
                  "received_subject": item.get("received_subject", "")})
        await db.job_opportunities.insert_one(doc.copy())
        created.append(doc)
    return {"created": created, "scanned": len(messages)}
