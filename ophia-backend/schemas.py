"""
schemas.py — request and response bodies for the API.

Every endpoint declares its response model, so /docs shows real schemas and
responses contain exactly these fields (anything else stored in Firestore,
such as embeddings, is dropped by FastAPI rather than leaked).
"""

from typing import Optional

from pydantic import BaseModel, Field

from state_machine import MatchStatus, ProvisioningStatus, WorkspaceStatus


# ── Requests ─────────────────────────────────────────────────────────────────

class ApproveRequest(BaseModel):
    contact_email: Optional[str] = Field(default=None, description="Who gets the intro email + invite")


class RejectRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=500, description="Why the admin rejected it")


# ── Responses ────────────────────────────────────────────────────────────────

class Health(BaseModel):
    status: str = Field(description="'ok' or 'degraded'")
    firestore: bool
    error: Optional[str] = None


class Stats(BaseModel):
    startups: int = Field(description="Active startups")
    mentors: int = Field(description="Available mentors")


class Startup(BaseModel):
    company_name: str
    description: str = ""
    long_description: Optional[str] = None
    batch: Optional[str] = None
    status: Optional[str] = None
    industry_tags: list[str] = []
    country: Optional[str] = None
    founders: list[dict] = []
    website: Optional[str] = None
    is_active: bool = True


class Mentor(BaseModel):
    name: str
    title: str = ""
    bio: str = ""
    industry_tags: list[str] = []
    skills: list[str] = []
    availability_hours: int = 0
    status: str = "Available"
    partnerships: int = 0
    country: Optional[str] = None
    linkedin: Optional[str] = None


class Grades(BaseModel):
    domain_fit: int = Field(ge=1, le=5, description="Knows the startup's industry and technology")
    need_fit: int = Field(ge=1, le=5, description="Skills address the startup's likely problems")
    market_fit: int = Field(ge=1, le=5, description="Knows the startup's customers and region")


class Match(BaseModel):
    match_id: str
    startup_name: str
    mentor_name: str
    status: MatchStatus
    synergy: int = Field(ge=0, le=100, description="Blended score: similarity percentile + Gemini rubric")
    insight: str = ""
    tags: list[str] = []
    grades: Optional[Grades] = Field(default=None, description="None if Gemini grading failed")
    similarity: Optional[float] = Field(default=None, description="Raw cosine similarity of the embeddings")
    similarity_percentile: Optional[float] = Field(default=None, ge=0, le=1,
                                                   description="Share of startup-mentor pairs this beats")
    startup_description: str = ""
    startup_batch: str = ""
    startup_country: str = ""
    mentor_title: str = ""
    created_at: str
    decided_at: Optional[str] = None
    reject_reason: Optional[str] = None
    workspace_id: Optional[str] = None


class Milestone(BaseModel):
    day: int
    objective: str
    completed: bool


class Workspace(BaseModel):
    doc_id: str
    match_id: Optional[str] = None
    workspace_name: str
    startup_name: str
    mentor_name: str
    synergy_score: int
    status: WorkspaceStatus
    active: bool
    lifecycle_start: str
    lifecycle_end: str
    milestones: list[Milestone]
    provisioning_status: ProvisioningStatus
    provisioning_errors: list[str] = []
    drive_folder_url: Optional[str] = None
    calendar_event_id: Optional[str] = None
    intro_email_sent: bool = False


class ApproveResult(BaseModel):
    workspace: Workspace
    created: bool = Field(description="False when the match was already approved (idempotent)")
