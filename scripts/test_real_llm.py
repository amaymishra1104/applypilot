#!/usr/bin/env python3
"""Run one real LLM match and one real email draft against the configured provider."""
import asyncio
import json
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / "backend" / ".env")
sys.path.insert(0, str(ROOT / "backend"))

import ai_service
from llm import get_llm_provider, get_default_model


async def main():
    provider_name = os.environ.get("LLM_PROVIDER", "gemini")
    model_name = os.environ.get("LLM_MODEL") or get_default_model()
    print(f"Testing real LLM call with Provider: {provider_name}, Model: {model_name}")

    provider = get_llm_provider()

    # 1. Real Match
    print("\n--- 1. Testing Opportunity Match (Structured JSON Schema) ---")
    job = {
        "job_title": "Senior Backend Engineer",
        "company_name": "Acme Corp",
        "required_skills": ["Python", "FastAPI", "MongoDB", "AsyncIO"],
        "experience_required": "4+ years",
        "description_summary": "Looking for a seasoned Python engineer to build and optimize high-throughput microservices using FastAPI and MongoDB.",
    }
    profiles = [
        {
            "id": "profile_backend",
            "title": "Senior Backend Engineer",
            "skills": ["Python", "FastAPI", "MongoDB", "PostgreSQL", "Docker"],
            "experience_required": "5 years",
            "notes": "Backend engineering lead with distributed systems experience.",
            "resume_text": "Experienced Python Backend Developer specializing in FastAPI, MongoDB, and high-performance microservices architecture.",
        },
        {
            "id": "profile_frontend",
            "title": "Frontend React Specialist",
            "skills": ["React", "TypeScript", "TailwindCSS"],
            "experience_required": "3 years",
            "notes": "Focuses on web UI/UX.",
            "resume_text": "Frontend engineer with React and UI component library design experience.",
        },
    ]

    match_result = await ai_service.match_opportunity(job, profiles, model=model_name)
    print("Match Result:")
    print(json.dumps(match_result, indent=2))
    assert match_result is not None, "Match call returned None"
    assert match_result.get("role_profile_id") == "profile_backend", f"Expected profile_backend, got {match_result.get('role_profile_id')}"

    # 2. Real Email Draft
    print("\n--- 2. Testing Application Email Draft (Structured JSON Schema) ---")
    context = {
        "job_title": "Senior Backend Engineer",
        "company_name": "Acme Corp",
        "job_description": "We need a Python developer who loves FastAPI and scalable databases.",
        "resume_text": "Senior Backend Engineer with 5+ years of Python and FastAPI production experience.",
        "tone": "confident",
        "hr_name": "Alex",
        "applicant_name": "Amay",
    }
    email_result = await ai_service.generate_application_email(context, model=model_name)
    print("Email Draft Result:")
    print(json.dumps(email_result, indent=2))
    assert email_result is not None, "Email draft returned None"
    assert "subject" in email_result and "body" in email_result, f"Malformed email result: {email_result}"

    print("\n[SUCCESS] Both real LLM calls succeeded with structured JSON schema output!")


if __name__ == "__main__":
    asyncio.run(main())
