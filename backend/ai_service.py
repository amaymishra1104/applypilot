import json
import logging
import os
import uuid

from emergentintegrations.llm.chat import LlmChat, UserMessage

logger = logging.getLogger(__name__)
DEFAULT_MODEL = "gpt-5.4"

_NO_FABRICATION = (
    "CRITICAL RULES: Use ONLY the facts provided in the input. Never invent, assume or exaggerate "
    "candidate achievements, projects, certifications, company research or qualifications. If a fact "
    "is unknown, omit it rather than guessing."
)


def _chat(system_message: str, model: str | None = None) -> LlmChat:
    key = os.environ.get("EMERGENT_LLM_KEY")
    if not key:
        raise RuntimeError("AI is not configured (EMERGENT_LLM_KEY missing)")
    chat = LlmChat(api_key=key, session_id=str(uuid.uuid4()), system_message=system_message)
    return chat.with_model("openai", model or DEFAULT_MODEL)


async def _ask_json(system_message: str, prompt: str, model: str | None = None):
    text = await _chat(system_message, model).send_message(UserMessage(text=prompt))
    try:
        return json.loads(text)
    except Exception:
        for opener, closer in (("{", "}"), ("[", "]")):
            start, end = text.find(opener), text.rfind(closer)
            if start != -1 and end > start:
                try:
                    return json.loads(text[start:end + 1])
                except Exception:
                    continue
    logger.error("AI returned unparseable JSON: %s", text[:300])
    return None


async def parse_job_description(raw_text: str, model: str | None = None) -> dict | None:
    system = (
        "You are a precise recruitment data extractor. Return STRICT JSON only. " + _NO_FABRICATION
    )
    prompt = (
        "Extract structured data from this job posting text. Return JSON with keys: "
        '{"company_name": str ("" if unknown), "job_title": str, "required_skills": [str], '
        '"experience_required": str (e.g. "3-5 years", "" if unknown), "description_summary": str (2-3 sentences)}. '
        "Only include skills explicitly mentioned in the text.\n\nJOB POSTING:\n" + raw_text[:12000]
    )
    return await _ask_json(system, prompt, model)


async def match_opportunity(job: dict, profiles: list[dict], model: str | None = None) -> dict | None:
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
            "resume_excerpt": (p.get("resume_text") or "")[:1500],
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
    return await _ask_json(system, prompt, model)


async def ats_analyze(resume_text: str, job: dict, model: str | None = None) -> dict | None:
    system = ("You are an ATS (Applicant Tracking System) analyzer. Return STRICT JSON only. " + _NO_FABRICATION)
    prompt = (
        "Analyze how well this resume would perform against the job in an ATS and for a human recruiter.\n\n"
        f"JOB: {job.get('job_title', '')} at {job.get('company_name', '')}\n"
        f"Required skills: {', '.join(job.get('required_skills', []))}\n"
        f"Description: {(job.get('description_summary') or job.get('job_description', ''))[:2500]}\n\n"
        f"RESUME:\n{resume_text[:6000]}\n\n"
        'Return JSON: {"score": int 0-100, "matched_keywords": [str], "missing_keywords": [str], '
        '"suggestions": [str] (max 4 concrete, honest suggestions), "verdict": str (one honest sentence)}.'
    )
    return await _ask_json(system, prompt, model)


async def generate_application_email(context: dict, model: str | None = None) -> dict | None:
    system = (
        "You are an expert career coach who writes job application emails. The emails must sound natural, "
        "professional, concise and genuinely human - never generic or copy-paste. " + _NO_FABRICATION
    )
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
        f"CANDIDATE RESUME CONTENT (the ONLY source of facts about the candidate):\n{context.get('resume_text', '')[:4500]}\n\n"
        f"TONE: {context.get('tone', 'professional')}\n"
        f"CANDIDATE NAME (for signature): {context.get('candidate_name', '')}\n\n"
        "Requirements: a specific subject line mentioning the role; a proper greeting using the HR name if available; "
        "1-2 sentence introduction stating the role applied for; 1 short paragraph highlighting ONLY resume-backed "
        "projects/skills that match THIS job's requirements; a clear application intent sentence; professional closing "
        "with candidate name. Keep the whole email under 180 words. Do not use placeholder text like [Project] - "
        "only reference what exists in the resume content above.\n\n"
        'Return JSON: {"subject": str, "body": str (plain text, \\n for line breaks)}.'
    )
    return await _ask_json(system, prompt, model)


async def generate_followup_email(context: dict, model: str | None = None) -> dict | None:
    system = ("You are an expert career coach writing polite follow-up emails. " + _NO_FABRICATION)
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
    return await _ask_json(system, prompt, model)


async def classify_reply(subject: str, body: str, model: str | None = None) -> dict | None:
    system = "You classify recruiter/HR email replies to job applications. Return STRICT JSON only."
    prompt = (
        "Classify this email reply to a job application.\n\n"
        f"SUBJECT: {subject}\n\nBODY:\n{body[:4000]}\n\n"
        'Return JSON: {"category": "interview"|"interested"|"rejection"|"auto_response"|"other", '
        '"summary": str (1-2 sentences, factual), "next_action": str (what the candidate should do next)}. '
        "interview = invites to an interview or scheduling; interested = positive/engaged reply; "
        "rejection = explicit or clear decline; auto_response = automated acknowledgment; other = anything else."
    )
    return await _ask_json(system, prompt, model)


async def research_company(company_name: str, model: str | None = None) -> dict | None:
    system = ("You are a careful business researcher. Return STRICT JSON only. " + _NO_FABRICATION)
    prompt = (
        f"Provide brief background on the company '{company_name}' based only on well-established general knowledge. "
        "If you are not confident about this specific company, say so honestly instead of guessing. "
        'Return JSON: {"background": str (2-4 sentences; write "Not enough reliable information" if unsure), '
        '"known_for": [str] (max 3), "confidence": "high"|"medium"|"low", '
        '"caveat": str (one line reminding this is general knowledge, not live research)}.'
    )
    return await _ask_json(system, prompt, model)


async def extract_opportunities_from_emails(messages: list[dict], model: str | None = None) -> list[dict]:
    system = ("You detect real hiring/job opportunities from emails. Return STRICT JSON only. " + _NO_FABRICATION)
    prompt = (
        "Below are recent inbox emails. Identify ones that represent a genuine job opportunity, recruiter outreach, "
        "interview invite or hiring discussion for the inbox owner. Ignore newsletters, job-board digests, "
        "marketing and spam.\n\nEMAILS:\n" + json.dumps(messages[:40], indent=1)[:20000] +
        '\n\nReturn JSON: {"opportunities": [{"company_name": str, "job_title": str, "required_skills": [str], '
        '"description_summary": str, "from_email": str, "received_subject": str}]} - empty list if none.'
    )
    result = await _ask_json(system, prompt, model)
    if isinstance(result, dict):
        return result.get("opportunities", []) or []
    return []
