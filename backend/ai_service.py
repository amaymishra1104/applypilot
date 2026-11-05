import json
import logging
import os
from typing import Optional

from llm import get_default_model, get_llm_provider
from llm.schemas import (
    ApplicationEmailDraft,
    ATSAnalysisResult,
    CompanyResearch,
    EmailOpportunitiesResult,
    FollowupEmailDraft,
    JobDescriptionParsed,
    OpportunityMatchResult,
    ReplyClassification,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = get_default_model()

_NO_FABRICATION = (
    "CRITICAL RULES: Use ONLY the facts provided in the input. Never invent, assume or exaggerate "
    "candidate achievements, projects, certifications, company research or qualifications. If a fact "
    "is unknown, omit it rather than guessing."
)


async def _ask_json(system_message: str, prompt: str, schema: Optional[type] = None, model: Optional[str] = None):
    try:
        provider = get_llm_provider()
        return await provider.generate_json(system=system_message, prompt=prompt, schema=schema, model=model)
    except RuntimeError as e:
        logger.error("AI provider not configured: %s", e)
        return None
    except Exception as e:
        logger.error("AI call failed: %s", e)
        return None


async def parse_job_description(raw_text: str, model: Optional[str] = None) -> Optional[dict]:
    system = "You are a precise recruitment data extractor. Return STRICT JSON only. " + _NO_FABRICATION
    prompt = (
        "Extract structured data from this job posting text. Return JSON with keys: "
        '{"company_name": str ("" if unknown), "job_title": str, "required_skills": [str], '
        '"experience_required": str (e.g. "3-5 years", "" if unknown), "description_summary": str (2-3 sentences)}. '
        "Only include skills explicitly mentioned in the text.\n\nJOB POSTING:\n" + raw_text[:12000]
    )
    return await _ask_json(system, prompt, schema=JobDescriptionParsed, model=model)


async def match_opportunity(job: dict, profiles: list[dict], model: Optional[str] = None) -> Optional[dict]:
    system = (
        "You are an expert technical recruiter who matches job requirements to candidate role profiles. "
        "Return STRICT JSON only. " + _NO_FABRICATION
    )
    profiles_payload = []
    for p in profiles:
        profiles_payload.append({
            "id": p["id"],
            "title": p["title"],
            "description": (p.get("description") or "")[:500],
            "skills": p.get("skills", []),
            "experience_required": p.get("experience_required") or "",
            "notes": (p.get("notes") or "")[:300],
            "resume_excerpt": (p.get("resume_text") or "")[:3000],
            "has_resume": bool(p.get("resume_text")),
        })
    prompt = (
        "JOB OPPORTUNITY:\n"
        f"Title: {job.get('job_title', '')}\nCompany: {job.get('company_name', '')}\n"
        f"Required skills: {', '.join(job.get('required_skills', []))}\n"
        f"Experience: {job.get('experience_required', 'not stated')}\n"
        f"Description: {job.get('description_summary') or job.get('job_description', '')[:2000]}\n\n"
        "CANDIDATE ROLE PROFILES (with resume excerpts):\n"
        + json.dumps(profiles_payload, indent=1) +
        "\n\nCompare the job requirements against every role profile. Pick the single best match. "
        'Return JSON: {"role_profile_id": str (id of best profile), "score": int 0-100 (resume/job fit), '
        '"confidence": "high"|"medium"|"low", "matched_skills": [str], "missing_skills": [str], '
        '"reasoning": str (2-4 sentences explaining exactly why this profile and its resume fit this job), '
        '"alternatives": [{"id": str, "title": str, "score": int, "reasoning": str}] (up to 2 other viable profiles)}. '
        "If NO profile is a reasonable fit (all below 40), set role_profile_id to the best one anyway but "
        "explain clearly in reasoning. Score honestly - do not inflate."
    )
    return await _ask_json(system, prompt, schema=OpportunityMatchResult, model=model)


async def ats_analyze(resume_text: str, job: dict, model: Optional[str] = None) -> Optional[dict]:
    system = "You are an ATS (Applicant Tracking System) analyzer. Return STRICT JSON only. " + _NO_FABRICATION
    prompt = (
        "Analyze how well this resume would perform against the job in an ATS and for a human recruiter.\n\n"
        f"JOB: {job.get('job_title', '')} at {job.get('company_name', '')}\n"
        f"Required skills: {', '.join(job.get('required_skills', []))}\n"
        f"Description: {(job.get('description_summary') or job.get('job_description', ''))[:2500]}\n\n"
        f"RESUME:\n{resume_text[:12000]}\n\n"
        'Return JSON: {"score": int 0-100, "matched_keywords": [str], "missing_keywords": [str], '
        '"suggestions": [str] (max 4 concrete, honest suggestions), "verdict": str (one honest sentence)}.'
    )
    return await _ask_json(system, prompt, schema=ATSAnalysisResult, model=model)


async def generate_application_email(context: dict, model: Optional[str] = None) -> Optional[dict]:
    system = (
        "You are an expert career coach who writes job application emails. The emails must sound natural, "
        "professional, concise and genuinely human - never generic or copy-paste. " + _NO_FABRICATION
    )
    allowed_links = context.get("allowed_links") or []
    links_clause = (
        "\nAUTHORIZED CANDIDATE LINKS (only these links may be referenced if relevant; do NOT invent any other links or URLs):\n"
        + "\n".join(allowed_links) if allowed_links else "\nAUTHORIZED CANDIDATE LINKS: None. Do NOT include any web links or URLs."
    )
    feedback_clause = f"\nREVISION FEEDBACK: {context['feedback']}\n" if context.get("feedback") else ""

    style_hint = context.get("style_hint")
    style_clause = f"\nSTYLE HINT FOR THIS EMAIL: {style_hint}\n" if style_hint else ""

    recent_openings = context.get("recent_openings") or []
    openings_clause = ""
    if recent_openings:
        openings_list = "\n".join(f"- \"{op}\"" for op in recent_openings[-10:])
        openings_clause = f"\nRECENT OPENING LINES IN THIS BATCH (do NOT reuse or paraphrase these openings):\n{openings_list}\n"

    prompt = (
        "Write a job application email for the candidate.\n\n"
        f"TO: {context.get('hr_name') or 'Hiring Team'}{(' (' + context['hr_email'] + ')') if context.get('hr_email') else ''}\n"
        f"COMPANY: {context.get('company_name', '')}\n"
        f"JOB TITLE: {context.get('job_title', '')}\n"
        f"JOB REQUIREMENTS: {', '.join(context.get('required_skills', []))}\n"
        f"JOB DESCRIPTION SUMMARY: {context.get('description_summary', '')[:1500]}\n"
        f"COMPANY BACKGROUND (use only if relevant, do not repeat verbatim): {context.get('company_background', '')[:600]}\n\n"
        f"CANDIDATE ROLE PROFILE: {context.get('role_title', '')}\n"
        f"CANDIDATE SKILLS: {', '.join(context.get('role_skills', []))}\n"
        f"CANDIDATE EXPERIENCE: {context.get('experience_required', '')}\n"
        f"CANDIDATE NOTES: {context.get('role_notes', '')[:500]}\n"
        f"MATCHED SKILLS FOR THIS JOB: {', '.join(context.get('matched_skills', []))}\n"
        f"CANDIDATE RESUME CONTENT (the ONLY source of facts about the candidate):\n{context.get('resume_text', '')[:8000]}\n\n"
        f"TONE: {context.get('tone', 'professional')}\n"
        f"CANDIDATE NAME: {context.get('candidate_name', '')}\n"
        f"{links_clause}\n"
        f"{style_clause}"
        f"{openings_clause}"
        f"{feedback_clause}\n"
        "Requirements:\n"
        "- A specific, non-empty subject line mentioning the target role.\n"
        "- A proper greeting using the HR name if provided (e.g. 'Dear Sarah,'). NEVER use 'Hiring Manager' when an HR contact name is given.\n"
        "- Vary your opening line across emails - do NOT always start with 'I am writing to express my interest in...' or 'I hope this email finds you well'. Use a direct, compelling opening tailored to the specific role and company.\n"
        "- Follow the STYLE HINT above if provided to craft a distinct, engaging opening.\n"
        "- Do NOT reuse or closely paraphrase any of the RECENT OPENING LINES listed above.\n"
        "- 1-2 sentence introduction stating the role applied for.\n"
        "- 1 short paragraph highlighting ONLY resume-backed projects/skills that directly match THIS job's requirements.\n"
        "- A clear application intent sentence.\n"
        "- A professional closing sign-off line (e.g. 'Best regards,').\n"
        "- Write ONLY the email body and closing line. Do NOT write a signature block, phone number, or social links at the end - the signature block is appended automatically server-side.\n"
        "- Do NOT include any placeholder text like [Company Name], {Role}, or brackets of any kind. State actual facts.\n"
        "- Do NOT include any URL or link that is not listed in AUTHORIZED CANDIDATE LINKS above.\n"
        "- Keep the generated body under 180 words.\n\n"
        'Return JSON: {"subject": str, "body": str (plain text, \\n for line breaks)}.'
    )
    return await _ask_json(system, prompt, schema=ApplicationEmailDraft, model=model)


async def generate_followup_email(context: dict, model: Optional[str] = None) -> Optional[dict]:
    system = "You are an expert career coach writing polite follow-up emails. " + _NO_FABRICATION
    prompt = (
        "Write a short, polite follow-up email for a job application that has received no reply.\n\n"
        f"COMPANY: {context.get('company_name', '')}\nROLE: {context.get('job_title', '')}\n"
        f"ORIGINAL SUBJECT: {context.get('original_subject', '')}\n"
        f"DAYS SINCE APPLICATION: {context.get('days_since', 4)}\n"
        f"TONE: {context.get('tone', 'professional')}\n"
        f"CANDIDATE NAME: {context.get('candidate_name', '')}\n\n"
        "Requirements: subject line must be a natural follow-up (not 'Re:' unless replying); reference the original "
        "application; 2-3 sentences max; restate interest briefly; polite closing. Do not sound desperate or pushy.\n\n"
        'Return JSON: {"subject": str, "body": str (plain text)}.'
    )
    return await _ask_json(system, prompt, schema=FollowupEmailDraft, model=model)


async def classify_reply(subject: str, body: str, model: Optional[str] = None) -> Optional[dict]:
    system = "You classify recruiter/HR email replies to job applications. Return STRICT JSON only."
    prompt = (
        "Classify this email reply to a job application.\n\n"
        f"SUBJECT: {subject}\n\nBODY:\n{body[:4000]}\n\n"
        'Return JSON: {"category": "interview"|"interested"|"rejection"|"auto_response"|"other", '
        '"summary": str (1-2 sentences, factual), "next_action": str (what the candidate should do next)}. '
        "interview = invites to an interview or scheduling; interested = positive/engaged reply; "
        "rejection = explicit or clear decline; auto_response = automated acknowledgment; other = anything else."
    )
    return await _ask_json(system, prompt, schema=ReplyClassification, model=model)


async def research_company(company_name: str, model: Optional[str] = None) -> Optional[dict]:
    system = "You are a careful business researcher. Return STRICT JSON only. " + _NO_FABRICATION
    prompt = (
        f"Provide brief background on the company '{company_name}' based only on well-established general knowledge. "
        "If you are not confident about this specific company, say so honestly instead of guessing. "
        'Return JSON: {"background": str (2-4 sentences; write "Not enough reliable information" if unsure), '
        '"known_for": [str] (max 3), "confidence": "high"|"medium"|"low", '
        '"caveat": str (one line reminding this is general knowledge, not live research)}.'
    )
    return await _ask_json(system, prompt, schema=CompanyResearch, model=model)


async def extract_opportunities_from_emails(messages: list[dict], model: Optional[str] = None) -> list[dict]:
    system = "You detect real hiring/job opportunities from emails. Return STRICT JSON only. " + _NO_FABRICATION
    prompt = (
        "Below are recent inbox emails. Identify ones that represent a genuine job opportunity, recruiter outreach, "
        "interview invite or hiring discussion for the inbox owner. Ignore newsletters, job-board digests, "
        "marketing and spam.\n\nEMAILS:\n" + json.dumps(messages[:40], indent=1)[:20000] +
        '\n\nReturn JSON: {"opportunities": [{"company_name": str, "job_title": str, "required_skills": [str], '
        '"description_summary": str, "from_email": str, "received_subject": str}]} - empty list if none.'
    )
    result = await _ask_json(system, prompt, schema=EmailOpportunitiesResult, model=model)
    if isinstance(result, dict):
        return result.get("opportunities", []) or []
    return []
