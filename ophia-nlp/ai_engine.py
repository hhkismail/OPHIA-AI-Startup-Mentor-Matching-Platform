"""
ai_engine.py — OPHIA Cognitive Engine (Ismail's module)

Public API:
    from ai_engine import generate_matches   # by startup name, reads Firestore
    from ai_engine import match_startup      # pure: startup dict + mentor dicts
    from ai_engine import get_embedding      # shared by embed_data.py / seed_db.py

Uses Vertex AI via ADC — all usage billed to GCP credits.
Clients are created lazily, so importing this module never needs credentials.
"""

import os
import json
from pathlib import Path
from typing import Optional

import numpy as np
from dotenv import load_dotenv

# One .env at the repo root, shared by every module
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# ── CONFIG ────────────────────────────────────────────────────────────────────
GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "ophia-guard-2030")
GCP_LOCATION   = os.getenv("GCP_LOCATION", "us-central1")
TOP_N_MATCHES  = 3

# Stored vectors in Firestore were made with this model. Query and stored
# vectors must come from the same model, so everything reads this one value.
EMBED_MODEL = os.getenv("EMBED_MODEL", "text-embedding-004")
GEN_MODEL   = os.getenv("GEN_MODEL", "gemini-3.1-flash-lite")

_client = None
_db = None


def get_client():
    """Vertex AI client (created on first use)."""
    global _client
    if _client is None:
        from google import genai
        _client = genai.Client(vertexai=True, project=GCP_PROJECT_ID, location=GCP_LOCATION)
    return _client


def _get_db():
    global _db
    if _db is None:
        from google.cloud import firestore
        _db = firestore.Client(project=GCP_PROJECT_ID)
    return _db


# ── GEMINI STRUCTURED OUTPUT SCHEMA ──────────────────────────────────────────
MATCH_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "synergy": {
            "type": "INTEGER",
            "description": "Match synergy score from 0 to 100"
        },
        "insight": {
            "type": "STRING",
            "description": "Exactly 2 sentences explaining why this mentor-startup pair works"
        },
        "tags": {
            "type": "ARRAY",
            "items": {"type": "STRING"},
            "description": "2-4 taxonomy overlap tags"
        },
    },
    "required": ["synergy", "insight", "tags"]
}

INSIGHT_PROMPT = """
You are OPHIA, an AI ecosystem orchestrator for an innovation platform.

Evaluate this mentor-startup match and return a structured assessment.

STARTUP:
- Name: {startup_name}
- Description: {startup_description}
- Industry Tags: {startup_tags}

MENTOR:
- Name: {mentor_name}
- Title: {mentor_title}
- Bio: {mentor_bio}
- Skills: {mentor_skills}

Instructions:
- synergy: Score from 0-100 reflecting how well this mentor's expertise fits the startup's needs.
  (90-100 = exceptional alignment, 70-89 = strong, 50-69 = moderate, below 50 = weak)
- insight: Write EXACTLY 2 sentences. First sentence explains the core expertise alignment.
  Second sentence explains what specific outcome this mentor can drive for the startup.
- tags: 2-4 short taxonomy tags that describe the overlap (e.g. "AI/ML", "B2B Sales", "Series A Ready").
"""


# ── CORE FUNCTIONS ────────────────────────────────────────────────────────────

def get_embedding(text: str) -> list[float]:
    """Embeds text with EMBED_MODEL. Returns [] on failure."""
    if not text:
        return []
    try:
        result = get_client().models.embed_content(model=EMBED_MODEL, contents=text)
        return list(result.embeddings[0].values)
    except Exception as e:
        print(f"[ai_engine] Embedding error: {e}")
        return []


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    a, b = np.asarray(vec_a, dtype=float), np.asarray(vec_b, dtype=float)
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return float(a @ b / denom) if denom else 0.0


def _get_gemini_insight(startup: dict, mentor: dict, similarity: float) -> dict:
    from google.genai import types

    prompt = INSIGHT_PROMPT.format(
        startup_name=startup.get("company_name", ""),
        startup_description=startup.get("description", ""),
        startup_tags=", ".join(startup.get("industry_tags", [])),
        mentor_name=mentor.get("name", ""),
        mentor_title=mentor.get("title", ""),
        mentor_bio=mentor.get("bio", ""),
        mentor_skills=", ".join(mentor.get("skills", []))
    )
    try:
        response = get_client().models.generate_content(
            model=GEN_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=MATCH_SCHEMA,
                temperature=0.3,
            )
        )
        data = json.loads(response.text)
        data["synergy"] = max(0, min(100, int(data.get("synergy", 0))))
        return data
    except Exception as e:
        # Fall back to the embedding score rather than a made-up constant
        print(f"[ai_engine] Gemini insight error: {e}")
        return {
            "synergy": max(0, min(100, round(similarity * 100))),
            "insight": (
                f"{mentor.get('name')}'s background is semantically close to "
                f"{startup.get('company_name')}'s focus area. "
                "AI explanation unavailable — score is based on embedding similarity only."
            ),
            "tags": startup.get("industry_tags", [])[:3]
        }


def match_startup(startup: dict, mentors: list[dict], top_n: int = TOP_N_MATCHES) -> list[dict]:
    """
    Ranks mentors for one startup by cosine similarity, then asks Gemini to
    score and explain the top N. Never raises — returns [] on failure.

    Each result matches the MatchResult schema plus `similarity` (0-1).
    """
    startup_vec = startup.get("description_embedding")
    if not startup_vec:
        print("[ai_engine] No stored embedding — re-embedding on the fly...")
        startup_vec = get_embedding(startup.get("description", ""))
    if not startup_vec:
        return []

    scored = [
        (_cosine_similarity(startup_vec, m.get("bio_embedding") or []), m)
        for m in mentors
    ]
    scored = [(s, m) for s, m in scored if s > 0]
    scored.sort(key=lambda x: x[0], reverse=True)

    results = []
    for similarity, mentor in scored[:top_n]:
        print(f"[ai_engine]  → Gemini insight: {mentor.get('name')}")
        insight_data = _get_gemini_insight(startup, mentor, similarity)
        results.append({
            "startup_name": startup.get("company_name"),
            "mentor_name":  mentor.get("name"),
            "synergy":      insight_data.get("synergy", 0),
            "insight":      insight_data.get("insight", ""),
            "tags":         insight_data.get("tags", []),
            "similarity":   round(similarity, 3),
        })
    results.sort(key=lambda r: r["synergy"], reverse=True)
    return results


def _fetch_startup(startup_name: str) -> Optional[dict]:
    try:
        docs = _get_db().collection("startups") \
                 .where("company_name", "==", startup_name) \
                 .limit(1) \
                 .stream()
        for doc in docs:
            return doc.to_dict()
        return None
    except Exception as e:
        print(f"[ai_engine] Firestore startup fetch error: {e}")
        return None


def _fetch_all_mentors() -> list[dict]:
    try:
        docs = _get_db().collection("mentors") \
                 .where("status", "==", "Available") \
                 .stream()
        return [doc.to_dict() for doc in docs]
    except Exception as e:
        print(f"[ai_engine] Firestore mentor fetch error: {e}")
        return []


def generate_matches(startup_name: str) -> list[dict]:
    """
    Takes a startup name, returns top N mentor matches from Firestore.
    Never raises — returns empty list on failure.
    """
    print(f"[ai_engine] Generating matches for: {startup_name}")

    startup = _fetch_startup(startup_name)
    if not startup:
        print(f"[ai_engine] Startup not found: {startup_name}")
        return []

    mentors = _fetch_all_mentors()
    if not mentors:
        print("[ai_engine] No available mentors found")
        return []

    results = match_startup(startup, mentors)
    print(f"[ai_engine] Done. {len(results)} matches returned.")
    return results
