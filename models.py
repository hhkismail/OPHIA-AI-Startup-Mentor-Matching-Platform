# ophia/models.py
from pydantic import BaseModel, Field, HttpUrl
from typing import List, Optional

# ── STARTUP SCHEMA ────────────────────────────────────────────────────────
class Founder(BaseModel):
    name: str
    bio: Optional[str] = None
    linkedin: Optional[HttpUrl] = None
    twitter: Optional[HttpUrl] = None

class Startup(BaseModel):
    company_name: str
    description: str = Field(..., description="1-2 sentences about what the company does")
    batch: str = Field(..., description="e.g., W21, S22 (Program equivalent)")
    status: str = Field(..., description="Active, Acquired, Inactive, Public")
    industry_tags: List[str]
    country: str
    founders: List[Founder]
    website: Optional[HttpUrl] = None
    is_active: bool = Field(default=True, description="Flag for orchestration system")
    description_embedding: Optional[List[float]] = Field(default=None, description="Vector embedding for matching")

# ── MENTOR SCHEMA ─────────────────────────────────────────────────────────
class Mentor(BaseModel):
    name: str
    title: str
    bio: str
    industry_tags: List[str] = Field(..., description="Should complement startup tags")
    skills: List[str] = Field(..., description="e.g., B2B Sales, AI Security")
    availability_hours: int = Field(..., description="Hours per month")
    linkedin: Optional[HttpUrl] = None
    status: str = Field(default="Available", description="Available or Active")
    partnerships: int = Field(default=0, description="Number of active linkages")
    bio_embedding: Optional[List[float]] = Field(default=None, description="Vector embedding for matching")

# ── ORCHESTRATION SCHEMA ──────────────────────────────────────────────────
class MatchResult(BaseModel):
    startup_name: str
    mentor_name: str
    synergy: int = Field(..., ge=0, le=100, description="Synergy score 0-100")
    insight: str = Field(..., description="Exactly 2 sentences explaining the match")
    tags: List[str] = Field(..., description="Taxonomy overlap tags")

class ApproveLinkageRequest(BaseModel):
    startup_name: str
    mentor_name: str
    synergy: int = Field(..., ge=0, le=100)
    contact_email: Optional[str] = Field(default=None, description="Who gets the intro email + invite")