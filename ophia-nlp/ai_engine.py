"""
ai_engine.py — matching and scoring.

    match_startup(startup, mentors)   shortlist by embedding similarity, Gemini grades
                                      the top N, blended synergy (used by the backend)
    get_embedding(text)               shared by embed_data.py and seed_db.py

No storage access: callers pass startups and mentors in. Uses Vertex AI via
Application Default Credentials; clients are created lazily, so importing
this module never needs credentials.
"""

import logging
import os
import json
import random
import threading
import time
from pathlib import Path
from typing import Optional

import numpy as np
from dotenv import load_dotenv

log = logging.getLogger(__name__)

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
# Newer Gemini models are only served from the "global" endpoint, while the
# embedding model is regional — so generation has its own location.
GEN_LOCATION = os.getenv("GEN_LOCATION", "global")

_clients = {}
_clients_lock = threading.Lock()


def get_client(location: str = GCP_LOCATION):
    """Vertex AI client for a location (created once, thread-safe).

    Without the lock, threads racing here each build a client; the extras get
    garbage-collected, which closes their HTTP connection mid-request
    ("Cannot send a request, as the client has been closed").
    """
    with _clients_lock:
        if location not in _clients:
            from google import genai
            _clients[location] = genai.Client(vertexai=True, project=GCP_PROJECT_ID, location=location)
        return _clients[location]


def get_gen_client():
    """Vertex AI client for Gemini text generation."""
    return get_client(GEN_LOCATION)


# ── SYNERGY SCORING ──────────────────────────────────────────────────────────
#
# synergy (0-100) = SIM_WEIGHT * similarity percentile + (1 - SIM_WEIGHT) * rubric
#
# Why not just ask Gemini for a 0-100 number? It gave 95-98 to almost every
# pair: LLMs are poor at picking calibrated numbers and lean positive when
# asked "why does this match work". Instead Gemini grades three criteria on a
# 1-5 scale with written anchors (and reasons first), and the code turns the
# grades into a number.
#
# Why a percentile, not raw cosine? With text-embedding-004 nearly all pairs
# land in 0.3-0.7 and unrelated pairs still score ~0.4, so raw similarity * 100
# is meaningless. The percentile says "better than X% of all startup-mentor
# pairs".
#
# SIM_WEIGHT, from eval_scoring.py (49 startups): any weight from 0.2 to 0.8
# re-ranks the top 3 equally well (final pick = intended mentor 86-88%, vs 73%
# for embeddings alone and 76% for the old 0-100 prompt). Differences in that
# range are 1-2 startups, i.e. noise. 0.4 gives the most distinct scores while
# a random mentor still averages ~36 instead of the old ~61.
SIM_WEIGHT = 0.4

# Percentiles 0,5,...,100 of cosine similarity over all 3,050 startup x mentor
# pairs in the seeded data. Used when the caller doesn't pass a fresh reference
# (build_similarity_reference). Regenerate if the data or EMBED_MODEL changes.
DEFAULT_SIM_REFERENCE = np.array([
    0.2403, 0.3232, 0.3429, 0.3541, 0.3628, 0.3704, 0.3777, 0.3845, 0.3902, 0.3976,
    0.4039, 0.4101, 0.4162, 0.4234, 0.4313, 0.4401, 0.4518, 0.4677, 0.4872, 0.5150,
    0.7053,
])

RUBRIC_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "reasoning": {
            "type": "STRING",
            "description": "2-4 sentences weighing fit AND gaps, written before grading"
        },
        "domain_fit": {"type": "INTEGER", "minimum": 1, "maximum": 5},
        "need_fit": {"type": "INTEGER", "minimum": 1, "maximum": 5},
        "market_fit": {"type": "INTEGER", "minimum": 1, "maximum": 5},
        "insight": {
            "type": "STRING",
            "description": "Exactly 2 sentences for the programme admin: the main reason for the "
                           "grade, then the biggest gap or what the mentor can concretely help with"
        },
        "tags": {
            "type": "ARRAY",
            "items": {"type": "STRING"},
            "description": "2-4 short tags for the actual overlap"
        },
    },
    "required": ["reasoning", "domain_fit", "need_fit", "market_fit", "insight", "tags"],
    # Generate the reasoning before the grades, so the grades follow from it
    "propertyOrdering": ["reasoning", "domain_fit", "need_fit", "market_fit", "insight", "tags"],
}

RUBRIC_PROMPT = """
You are a strict reviewer for a startup accelerator, checking a proposed
mentor-startup pairing before an administrator approves it. Most proposed
pairings are mediocre; only give a 5 when the fit is specific and obvious.

STARTUP:
- Name: {startup_name}
- Description: {startup_description}
- Industry Tags: {startup_tags}
- Country: {startup_country}

MENTOR:
- Name: {mentor_name}
- Title: {mentor_title}
- Bio: {mentor_bio}
- Skills / industries: {mentor_skills}

Grade each criterion from 1 to 5:

domain_fit — does the mentor know the startup's industry and technology?
  5 = has built or run a company in this exact space
  3 = adjacent industry, or the right industry but a different technology
  1 = unrelated industry

need_fit — can the mentor's skills solve this startup's most likely problems at its stage?
  5 = their skills target this startup's biggest current challenge
  3 = generally useful (fundraising, growth) but not specific to it
  1 = their skills don't address what this startup needs

market_fit — does the mentor know the startup's customers and region?
  5 = same customer segment and same region
  3 = same customer segment or same region, not both
  1 = neither

First write your reasoning, including any gaps, then grade.
"""

def build_similarity_reference(startups: list[dict], mentors: list[dict]) -> np.ndarray:
    """Percentiles 0,5,...,100 of cosine similarity over every startup x mentor pair."""
    a = np.array([s["description_embedding"] for s in startups if s.get("description_embedding")], dtype=float)
    b = np.array([m["bio_embedding"] for m in mentors if m.get("bio_embedding")], dtype=float)
    a /= np.linalg.norm(a, axis=1, keepdims=True)
    b /= np.linalg.norm(b, axis=1, keepdims=True)
    return np.percentile(a @ b.T, np.arange(0, 101, 5))


def similarity_percentile(similarity: float, reference=None) -> float:
    """0-1: share of startup-mentor pairs this similarity beats."""
    ref = DEFAULT_SIM_REFERENCE if reference is None else reference
    return float(np.interp(similarity, ref, np.linspace(0, 1, len(ref))))


def rubric_score(grades: dict) -> float:
    """0-1 from three 1-5 grades."""
    vals = [max(1, min(5, int(grades[k]))) for k in ("domain_fit", "need_fit", "market_fit")]
    return (sum(vals) / len(vals) - 1) / 4


# Domain gate, adopted after a pre-registered held-out test (eval_human.py,
# commit 91afa6c). Human labels showed the AI was too generous to mentors from
# the wrong industry: averaging let generic need/market grades lift a poor
# domain_fit into the "ok" range. With domain_fit <= 2 the score is capped
# below MIN_SYNERGY, so such pairs are never suggested. On 20 fresh labelled
# pairs: weighted kappa 0.64 -> 0.96; 9 of the 10 pairs it changed were "bad".
DOMAIN_GATE_MAX_FIT = 2
DOMAIN_GATE_CAP = 49


def apply_domain_gate(synergy: int, grades: dict | None) -> int:
    if grades and grades["domain_fit"] <= DOMAIN_GATE_MAX_FIT:
        return min(synergy, DOMAIN_GATE_CAP)
    return synergy


def blend_synergy(sim_pct: float, rubric: float | None, sim_weight: float = SIM_WEIGHT) -> int:
    """Final 0-100 synergy. Without a rubric (Gemini failed) it's similarity only."""
    if rubric is None:
        return round(100 * sim_pct)
    return round(100 * (sim_weight * sim_pct + (1 - sim_weight) * rubric))


# ── CORE FUNCTIONS ────────────────────────────────────────────────────────────

# What gets embedded. A one-line slogan ("Make undruggable targets a thing of
# the past") carries too little meaning to match on, so include the long
# description and tags. Stored vectors must be built with these same recipes.
def startup_embedding_text(startup: dict) -> str:
    parts = [startup.get("description"), startup.get("long_description")]
    if startup.get("industry_tags"):
        parts.append("Industries: " + ", ".join(startup["industry_tags"]))
    return "\n".join(p for p in parts if p)


def mentor_embedding_text(mentor: dict) -> str:
    parts = [mentor.get("title"), mentor.get("bio")]
    expertise = list(dict.fromkeys(mentor.get("skills", []) + mentor.get("industry_tags", [])))
    if expertise:
        parts.append("Expertise: " + ", ".join(expertise))
    return "\n".join(p for p in parts if p)


def get_embedding(text: str) -> list[float]:
    """Embeds text with EMBED_MODEL. Returns [] on failure."""
    if not text:
        return []
    try:
        result = get_client().models.embed_content(model=EMBED_MODEL, contents=text)
        return list(result.embeddings[0].values)
    except Exception as e:
        log.warning(f"Embedding error: {e}")
        return []


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    a, b = np.asarray(vec_a, dtype=float), np.asarray(vec_b, dtype=float)
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return float(a @ b / denom) if denom else 0.0


def generate_with_retry(retries: int = 5, **kwargs):
    """generate_content with exponential backoff on 429 rate limits."""
    for attempt in range(retries):
        try:
            return get_gen_client().models.generate_content(**kwargs)
        except Exception as e:
            if "429" not in str(e) or attempt == retries - 1:
                raise
            time.sleep(2 ** attempt + random.random())


_grade_cache: dict[str, dict] = {}


def grade_pair(startup: dict, mentor: dict) -> Optional[dict]:
    """Gemini's rubric grades + insight + tags for one pair, or None on failure.

    Successful grades are cached per (prompt, model): grading is deterministic
    (temperature 0), and a startup left unassigned would otherwise be
    re-graded every time suggestions are topped up.
    """
    from google.genai import types

    prompt = RUBRIC_PROMPT.format(
        startup_name=startup.get("company_name", ""),
        startup_description=startup_embedding_text(startup),
        startup_tags=", ".join(startup.get("industry_tags", [])),
        startup_country=startup.get("country", "unknown"),
        mentor_name=mentor.get("name", ""),
        mentor_title=mentor.get("title", ""),
        mentor_bio=mentor.get("bio", ""),
        mentor_skills=", ".join(dict.fromkeys(mentor.get("skills", []) + mentor.get("industry_tags", []))),
    )
    cache_key = f"{GEN_MODEL}\n{prompt}"
    if cache_key in _grade_cache:
        return dict(_grade_cache[cache_key])
    try:
        response = generate_with_retry(
            model=GEN_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=RUBRIC_SCHEMA,
                temperature=0,
            )
        )
        grades = json.loads(response.text)
        rubric_score(grades)  # validates the three grades are present
        _grade_cache[cache_key] = grades
        return dict(grades)
    except Exception as e:
        log.warning(f"Gemini grading error: {e}")
        return None


def score_pair(startup: dict, mentor: dict, similarity: float, reference=None) -> dict:
    """Synergy, insight and tags for one pair. Falls back to similarity only."""
    sim_pct = similarity_percentile(similarity, reference)
    grades = grade_pair(startup, mentor)
    if grades is None:
        return {
            "synergy": blend_synergy(sim_pct, None),
            "insight": (
                f"{mentor.get('name')}'s profile is closer to {startup.get('company_name')} "
                f"than {round(100 * sim_pct)}% of startup-mentor pairs. "
                "AI review unavailable — score is based on embedding similarity only."
            ),
            "tags": startup.get("industry_tags", [])[:3],
            "grades": None,
        }
    return {
        "synergy": apply_domain_gate(blend_synergy(sim_pct, rubric_score(grades)), grades),
        "insight": grades["insight"],
        "tags": grades.get("tags", []),
        "grades": {k: grades[k] for k in ("domain_fit", "need_fit", "market_fit")},
    }


def match_startup(startup: dict, mentors: list[dict], top_n: int = TOP_N_MATCHES,
                  reference=None) -> list[dict]:
    """
    Ranks mentors for one startup by cosine similarity, then has Gemini grade
    the top N, and sorts them by blended synergy. Never raises — returns [] on
    failure. `reference` is from build_similarity_reference (default: built-in).

    Each result: startup_name, mentor_name, synergy (0-100), insight, tags,
    similarity (raw cosine), similarity_percentile (0-1) and grades (the
    rubric, or None if Gemini failed).
    """
    startup_vec = startup.get("description_embedding")
    if not startup_vec:
        log.info("No stored embedding — re-embedding on the fly...")
        startup_vec = get_embedding(startup_embedding_text(startup))
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
        log.debug(f"Gemini grading: {mentor.get('name')}")
        scored_pair = score_pair(startup, mentor, similarity, reference)
        results.append({
            "startup_name": startup.get("company_name"),
            "mentor_name":  mentor.get("name"),
            "synergy":      scored_pair["synergy"],
            "insight":      scored_pair["insight"],
            "tags":         scored_pair["tags"],
            "similarity":   round(similarity, 3),
            "similarity_percentile": round(similarity_percentile(similarity, reference), 3),
            "grades":       scored_pair["grades"],
        })
    results.sort(key=lambda r: r["synergy"], reverse=True)
    return results
