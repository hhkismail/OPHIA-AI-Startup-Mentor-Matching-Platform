# models.py — request bodies for the backend API (ophia-backend/app.py)
from typing import Optional

from pydantic import BaseModel, Field


class ApproveRequest(BaseModel):
    contact_email: Optional[str] = Field(default=None, description="Who gets the intro email + invite")


class RejectRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=500, description="Why the admin rejected it")
