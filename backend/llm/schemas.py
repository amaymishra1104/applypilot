from typing import List, Optional
from pydantic import BaseModel, Field


class JobDescriptionParsed(BaseModel):
    company_name: str = Field(default="", description="Company name or empty if unknown")
    job_title: str = Field(default="", description="Job title")
    required_skills: List[str] = Field(default_factory=list, description="Skills explicitly required")
    experience_required: str = Field(default="", description="Experience required or empty")
    description_summary: str = Field(default="", description="2-3 sentence factual summary")


class MatchAlternative(BaseModel):
    id: str = Field(description="Role profile ID")
    title: str = Field(description="Role profile title")
    score: int = Field(description="Fit score 0-100")
    reasoning: str = Field(description="Reasoning for fit")


class OpportunityMatchResult(BaseModel):
    role_profile_id: str = Field(description="ID of the best matching role profile")
    score: int = Field(description="Match score 0-100")
    confidence: str = Field(description="high, medium, or low")
    matched_skills: List[str] = Field(default_factory=list)
    missing_skills: List[str] = Field(default_factory=list)
    reasoning: str = Field(description="Explanation of match")
    alternatives: List[MatchAlternative] = Field(default_factory=list)


class ATSAnalysisResult(BaseModel):
    score: int = Field(description="ATS match score 0-100")
    matched_keywords: List[str] = Field(default_factory=list)
    missing_keywords: List[str] = Field(default_factory=list)
    suggestions: List[str] = Field(default_factory=list)
    verdict: str = Field(description="One honest sentence verdict")


class ApplicationEmailDraft(BaseModel):
    subject: str = Field(description="Specific email subject line")
    body: str = Field(description="Email body with plain text line breaks")


class FollowupEmailDraft(BaseModel):
    subject: str = Field(description="Follow-up subject line")
    body: str = Field(description="Polite follow-up body text")


class ReplyClassification(BaseModel):
    category: str = Field(description="interview, interested, rejection, auto_response, or other")
    summary: str = Field(description="1-2 sentence factual summary")
    next_action: str = Field(description="Recommended next action for candidate")


class CompanyResearch(BaseModel):
    background: str = Field(description="2-4 sentences on company background")
    known_for: List[str] = Field(default_factory=list)
    confidence: str = Field(description="high, medium, or low")
    caveat: str = Field(description="Caveat note on general knowledge")


class ExtractedOpportunity(BaseModel):
    company_name: str = Field(default="")
    job_title: str = Field(default="")
    required_skills: List[str] = Field(default_factory=list)
    description_summary: str = Field(default="")
    from_email: str = Field(default="")
    received_subject: str = Field(default="")


class EmailOpportunitiesResult(BaseModel):
    opportunities: List[ExtractedOpportunity] = Field(default_factory=list)
