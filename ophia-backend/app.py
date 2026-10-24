"""
OPHIA Core Orchestration Engine — FastAPI backend.

Connects the pieces:
  Firestore (ophia-data/database.py)  →  AI matching (ophia-nlp/ai_engine.py)
  →  admin approval  →  Gmail/Drive/Calendar (ophia-data/workspace_trigger.py)

Run (from ophia-backend/):
  uvicorn app:app --reload        # or: python app.py
Docs at http://localhost:8000/docs
"""

import os
import sys
from pathlib import Path
from typing import List

from fastapi import BackgroundTasks, FastAPI, HTTPException

# Log lines contain emoji/arrows; on Windows a redirected stdout uses cp1252
# and print() would crash the request. Never let logging kill a request.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parent.parent
for p in (REPO_ROOT, REPO_ROOT / "ophia-nlp", REPO_ROOT / "ophia-data"):
    sys.path.insert(0, str(p))

import database                                   # noqa: E402
from ai_engine import build_similarity_reference, match_startup  # noqa: E402
from models import ApproveLinkageRequest          # noqa: E402

app = FastAPI(title="OPHIA Core Orchestration Engine")

# Gemini calls are slow and cost money, so pending matches are cached until
# ?refresh=true or until something is approved.
_linkage_cache: dict[int, list] = {}


def _db_call(fn, *args):
    """Runs a database function, turning connection problems into a clear 503."""
    try:
        return fn(*args)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Firestore unavailable: {e}")


def _strip_embeddings(record: dict) -> dict:
    return {k: v for k, v in record.items() if not k.endswith("_embedding")}


# ── ROUTES ────────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    try:
        database.get_db()
        return {"status": "ok", "firestore": True}
    except Exception as e:
        return {"status": "degraded", "firestore": False, "error": str(e)}


@app.get("/api/startups")
def list_startups():
    return [_strip_embeddings(s) for s in _db_call(database.get_all_startups)]


@app.get("/api/mentors")
def list_mentors():
    return [_strip_embeddings(m) for m in _db_call(database.get_all_mentors)]


@app.get("/api/workspaces")
def list_workspaces():
    """Approved matches (90-day programmable entities)."""
    return _db_call(database.get_all_active_entities)


@app.get("/api/linkages")
def fetch_pending_linkages(limit: int = 5, refresh: bool = False):
    """
    Best mentor for each of up to `limit` active startups that don't already
    have an active workspace. Each item is a MatchResult plus display fields.
    """
    if refresh:
        _linkage_cache.clear()
    elif limit in _linkage_cache:
        return _linkage_cache[limit]

    startups = _db_call(database.get_active_startups)
    mentors = _db_call(database.get_available_mentors)
    if not mentors:
        raise HTTPException(status_code=404, detail="No available mentors — run ophia-data/seed_db.py")

    already_matched = {e["startup_name"] for e in _db_call(database.get_all_active_entities)}
    mentor_titles = {m["name"]: m.get("title", "") for m in mentors}
    # Similarity percentiles relative to the current data, not a stale snapshot
    reference = build_similarity_reference(startups, mentors) if startups else None

    linkages = []
    for startup in startups:
        if len(linkages) >= limit:
            break
        if startup["company_name"] in already_matched:
            continue
        # Grade the top 3 by similarity, keep the best by blended synergy
        matches = match_startup(startup, mentors, top_n=3, reference=reference)
        if not matches:
            continue
        best = matches[0]
        linkages.append({
            **best,
            "startup_description": startup.get("description", ""),
            "startup_batch": startup.get("batch", ""),
            "startup_country": startup.get("country", ""),
            "mentor_title": mentor_titles.get(best["mentor_name"], ""),
        })

    _linkage_cache[limit] = linkages
    return linkages


def _provision_workspace(entity_id: str, req: ApproveLinkageRequest):
    """Background task: email + Drive + Calendar, then store the results."""
    from workspace_trigger import TOKEN_PATH, trigger_workspace_automation

    # The first Google login opens a browser, which can't happen inside the
    # server. Run `python ophia-data/workspace_trigger.py` once to create it.
    if not os.path.exists(TOKEN_PATH):
        print(f"[backend] Skipping Workspace automation for {entity_id}: no {TOKEN_PATH}. "
              "Run `python ophia-data/workspace_trigger.py` once to log in.")
        return

    result = trigger_workspace_automation(
        startup_name=req.startup_name,
        mentor_name=req.mentor_name,
        synergy_score=req.synergy,
        contact_email=req.contact_email,
    )
    database.update_entity_workspace_urls(
        entity_id,
        drive_url=result.get("drive_folder_url"),
        calendar_event_id=result.get("calendar_event_id"),
        email_sent=result.get("email_sent", False),
    )


@app.post("/api/linkages/approve")
def approve_linkages(payloads: List[ApproveLinkageRequest], background_tasks: BackgroundTasks):
    """
    Creates a 90-day active entity in Firestore for each approved match, then
    runs the Google Workspace automation in the background.
    """
    created = []
    for req in payloads:
        entity_id = _db_call(database.create_active_entity, req.startup_name, req.mentor_name, req.synergy)
        background_tasks.add_task(_provision_workspace, entity_id, req)
        created.append({"entity_id": entity_id, "startup_name": req.startup_name,
                        "mentor_name": req.mentor_name})

    _linkage_cache.clear()
    return {"message": "Success", "provisioned_entities": created}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", "8000")))
