"""
OPHIA Core Orchestration Engine — FastAPI backend.

Connects the pieces:
  Firestore (repository.py)  →  AI matching (ophia-nlp/ai_engine.py)
  →  admin approve/reject (state_machine.py)  →  Gmail/Drive/Calendar
  (ophia-data/workspace_trigger.py)

Run (from ophia-backend/):
  uvicorn app:app --reload        # or: python app.py
Docs at http://localhost:8000/docs
"""

import hmac
import logging
import os
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request, Security
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader

REPO_ROOT = Path(__file__).resolve().parent.parent
for p in (REPO_ROOT / "ophia-nlp", REPO_ROOT / "ophia-data"):
    sys.path.insert(0, str(p))

import database                                                  # noqa: E402
import state_machine as sm                                       # noqa: E402
from ai_engine import build_similarity_reference, match_startup  # noqa: E402
from assignment import assign_optimal, mentor_capacity           # noqa: E402
from schemas import (ApproveRequest, ApproveResult, Health, Match, Mentor,  # noqa: E402
                     RejectRequest, Startup, Stats, Workspace)
from repository import FirestoreRepository, NotFound, Repository, new_match  # noqa: E402

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
log = logging.getLogger("ophia.backend")

app = FastAPI(title="OPHIA Core Orchestration Engine")


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """One line per request: method, path, status and duration."""
    start = time.perf_counter()
    response = await call_next(request)
    log.info("%s %s -> %d (%.0f ms)", request.method, request.url.path, response.status_code,
             (time.perf_counter() - start) * 1000)
    return response

# Suggestions below this synergy are not made; the startup waits for capacity
MIN_SYNERGY = int(os.getenv("MIN_SYNERGY", "50"))
# Parallel Gemini grading calls when generating a batch of suggestions
GRADING_WORKERS = int(os.getenv("GRADING_WORKERS", "8"))


def suggestions_enabled() -> bool:
    """Cost switch: SUGGEST_NEW_MATCHES=false never calls Gemini, only serves stored suggestions."""
    return os.getenv("SUGGEST_NEW_MATCHES", "true").strip().lower() not in ("false", "0", "no")

_repo = FirestoreRepository(database)


def get_repo() -> Repository:
    """Storage dependency; tests override it with an InMemoryRepository."""
    return _repo


# ── AUTH ─────────────────────────────────────────────────────────────────────
# One shared admin key (ADMIN_API_KEY in .env), sent as the X-API-Key header.
# Everything that changes data, or spends money on Gemini, requires it.
# Reads stay open so a public demo can show the dashboard.

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False,
                               description="Admin key (ADMIN_API_KEY on the server)")


def is_admin(key: Optional[str] = Security(_api_key_header)) -> bool:
    expected = os.getenv("ADMIN_API_KEY", "")
    # compare_digest takes the same time whether the first or last character
    # differs, so the key can't be guessed from response timings
    return bool(expected and key and hmac.compare_digest(key.encode(), expected.encode()))


def require_admin(key: Optional[str] = Security(_api_key_header)):
    if not os.getenv("ADMIN_API_KEY"):
        # Fail closed: a server with no key configured accepts no changes
        raise HTTPException(status_code=503, detail="Server has no ADMIN_API_KEY configured; changes are disabled")
    if not is_admin(key):
        raise HTTPException(status_code=401, detail="Missing or invalid X-API-Key",
                            headers={"WWW-Authenticate": "ApiKey"})


ADMIN_ONLY = [Depends(require_admin)]


@app.exception_handler(sm.InvalidTransition)
def invalid_transition(request: Request, exc: sm.InvalidTransition):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(NotFound)
def not_found(request: Request, exc: NotFound):
    return JSONResponse(status_code=404, content={"detail": exc.args[0]})


def _db_call(fn, *args):
    """Runs a storage call, turning connection problems into a clear 503."""
    try:
        return fn(*args)
    except (sm.InvalidTransition, NotFound):
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Firestore unavailable: {e}")



# ── READ ─────────────────────────────────────────────────────────────────────

@app.get("/api/health", response_model=Health)
def health():
    try:
        database.get_db()
        return {"status": "ok", "firestore": True}
    except Exception as e:
        return {"status": "degraded", "firestore": False, "error": str(e)}


@app.get("/api/startups", response_model=list[Startup])
def list_startups(repo: Repository = Depends(get_repo)):
    return _db_call(repo.all_startups)


@app.get("/api/mentors", response_model=list[Mentor])
def list_mentors(repo: Repository = Depends(get_repo)):
    return _db_call(repo.all_mentors)


@app.get("/api/stats", response_model=Stats)
def stats(repo: Repository = Depends(get_repo)):
    """Counts for the dashboard header."""
    return {
        "startups": len(_db_call(repo.active_startups)),
        "mentors": len(_db_call(repo.available_mentors)),
    }


@app.get("/api/matches", response_model=list[Match])
def list_matches(status: Optional[sm.MatchStatus] = None, repo: Repository = Depends(get_repo)):
    """Every suggested match with its decision — the record of admin choices."""
    return _db_call(repo.matches, status.value if status else None)


@app.get("/api/workspaces", response_model=list[Workspace])
def list_workspaces(repo: Repository = Depends(get_repo)):
    """Approved matches: 90-day workspaces (active, completed or cancelled)."""
    return _db_call(repo.workspaces)


# ── MATCHING ─────────────────────────────────────────────────────────────────

@app.get("/api/linkages", response_model=list[Match])
def pending_linkages(limit: int = Query(5, ge=1, le=50), refresh: bool = False,
                     repo: Repository = Depends(get_repo), admin: bool = Depends(is_admin)):
    """
    Pending matches awaiting a decision, topped up to `limit` with new
    suggestions for startups that have no pending or approved match.
    Suggestions are stored, so Gemini runs once per startup, not per page load.
    `refresh=true` discards pending suggestions and generates fresh ones.
    Mentors an admin rejected for a startup are never suggested to it again.

    Without the admin key this only returns stored suggestions: generating
    new ones costs Gemini calls, so anonymous visitors can't trigger it.
    With SUGGEST_NEW_MATCHES=false nobody can.
    """
    if refresh:
        if not admin:
            require_admin(None)  # raises 401/503
        if not suggestions_enabled():
            raise HTTPException(status_code=503, detail="New suggestions are disabled (SUGGEST_NEW_MATCHES=false)")
        _db_call(repo.delete_pending_matches)

    matches = _db_call(repo.matches)
    pending = [m for m in matches if m["status"] == sm.MatchStatus.PENDING.value]
    if admin and suggestions_enabled() and len(pending) < limit:
        pending += _suggest(repo, matches)
    return sorted(pending, key=lambda m: m["created_at"])[:limit]


def _suggest(repo: Repository, existing: list[dict]) -> list[dict]:
    """
    Suggests mentors for every startup without a pending or approved match,
    jointly, so no mentor is suggested beyond their capacity (assignment.py).
    Capacity already counts active workspaces and still-pending suggestions.
    """
    startups = _db_call(repo.active_startups)
    mentors = _db_call(repo.available_mentors)
    if not mentors:
        raise HTTPException(status_code=404, detail="No available mentors — run ophia-data/seed_db.py")

    decided = {m["startup_name"] for m in existing if m["status"] != sm.MatchStatus.REJECTED.value}
    rejected = {(m["startup_name"], m["mentor_name"]) for m in existing
                if m["status"] == sm.MatchStatus.REJECTED.value}
    eligible = [s for s in startups if s["company_name"] not in decided]
    if not eligible:
        return []

    load = Counter(w["mentor_name"] for w in _db_call(repo.workspaces)
                   if w["status"] == sm.WorkspaceStatus.ACTIVE.value)
    load.update(m["mentor_name"] for m in existing if m["status"] == sm.MatchStatus.PENDING.value)
    capacity = {m["name"]: mentor_capacity(m, load[m["name"]]) for m in mentors}
    mentor_titles = {m["name"]: m.get("title", "") for m in mentors}
    # Similarity percentiles relative to the current data, not a stale snapshot
    reference = build_similarity_reference(startups, mentors)

    def candidates(startup):
        name = startup["company_name"]
        allowed = [m for m in mentors if (name, m["name"]) not in rejected and capacity[m["name"]] > 0]
        # The top 3 by similarity get graded by Gemini; the assignment picks among them
        return startup, match_startup(startup, allowed, top_n=3, reference=reference)

    with ThreadPoolExecutor(GRADING_WORKERS) as pool:
        graded = list(pool.map(candidates, eligible))

    results = {(r["startup_name"], r["mentor_name"]): r for _, rs in graded for r in rs}
    chosen = assign_optimal({pair: r["synergy"] for pair, r in results.items()}, capacity,
                            min_synergy=MIN_SYNERGY)
    by_name = {s["company_name"]: s for s, _ in graded}

    new = [new_match({
        **results[(startup_name, mentor_name)],
        "startup_description": by_name[startup_name].get("description", ""),
        "startup_batch": by_name[startup_name].get("batch", ""),
        "startup_country": by_name[startup_name].get("country", ""),
        "mentor_title": mentor_titles.get(mentor_name, ""),
    }) for startup_name, mentor_name in chosen.items()]
    unassigned = len(eligible) - len(new)
    if unassigned:
        log.info("%d startup(s) got no suggestion: no candidate mentor with free capacity "
                 "scored >= %d", unassigned, MIN_SYNERGY)
    _db_call(repo.add_matches, new)
    return new


# ── DECISIONS ────────────────────────────────────────────────────────────────

@app.post("/api/matches/{match_id}/approve", dependencies=ADMIN_ONLY, response_model=ApproveResult)
def approve_match(match_id: str, background_tasks: BackgroundTasks,
                  body: Optional[ApproveRequest] = None, repo: Repository = Depends(get_repo)):
    """
    Approves a pending match and creates its 90-day workspace, then runs the
    Google Workspace automation in the background. Idempotent: approving an
    approved match returns the existing workspace (created=false).
    """
    workspace, created = _db_call(repo.approve_match, match_id)
    if created:
        background_tasks.add_task(_provision_workspace, repo, workspace["doc_id"],
                                  body.contact_email if body else None)
    return {"workspace": workspace, "created": created}


@app.post("/api/matches/{match_id}/reject", dependencies=ADMIN_ONLY, response_model=Match)
def reject_match(match_id: str, body: Optional[RejectRequest] = None, repo: Repository = Depends(get_repo)):
    return _db_call(repo.reject_match, match_id, body.reason if body else None)


# ── WORKSPACES ───────────────────────────────────────────────────────────────

@app.post("/api/workspaces/{workspace_id}/milestones/{day}/complete", dependencies=ADMIN_ONLY,
          response_model=Workspace)
def complete_milestone(workspace_id: str, day: int, repo: Repository = Depends(get_repo)):
    """Milestones complete in order; the last one completes the workspace."""
    def change(ws):
        milestones, status = sm.complete_milestone(ws["status"], ws["milestones"], day)
        return {"milestones": milestones, "status": status.value,
                "active": status == sm.WorkspaceStatus.ACTIVE}
    return _db_call(repo.update_workspace, workspace_id, change)


@app.post("/api/workspaces/{workspace_id}/cancel", dependencies=ADMIN_ONLY, response_model=Workspace)
def cancel_workspace(workspace_id: str, repo: Repository = Depends(get_repo)):
    def change(ws):
        status = sm.transition_workspace(ws["status"], sm.WorkspaceStatus.CANCELLED)
        return {"status": status.value, "active": False}
    return _db_call(repo.update_workspace, workspace_id, change)


@app.post("/api/workspaces/{workspace_id}/provision", dependencies=ADMIN_ONLY, response_model=Workspace)
def retry_provisioning(workspace_id: str, background_tasks: BackgroundTasks,
                       body: Optional[ApproveRequest] = None, repo: Repository = Depends(get_repo)):
    """Re-runs email/Drive/Calendar for a workspace whose provisioning didn't fully succeed."""
    def change(ws):
        status = sm.transition_provisioning(ws["provisioning_status"], sm.ProvisioningStatus.QUEUED)
        return {"provisioning_status": status.value, "provisioning_errors": []}
    workspace = _db_call(repo.update_workspace, workspace_id, change)
    background_tasks.add_task(_provision_workspace, repo, workspace_id, body.contact_email if body else None)
    return workspace


def _provision_workspace(repo: Repository, workspace_id: str, contact_email: Optional[str]):
    """Background task: email + Drive + Calendar, then record the outcome."""
    from workspace_trigger import TOKEN_PATH, trigger_workspace_automation

    def finish(outcome: sm.ProvisioningStatus, **fields):
        def change(ws):
            status = sm.transition_provisioning(ws["provisioning_status"], outcome)
            return {"provisioning_status": status.value, **fields}
        repo.update_workspace(workspace_id, change)

    # The first Google login opens a browser, which can't happen inside the
    # server. Run `python ophia-data/workspace_trigger.py` once to create it.
    if not os.path.exists(TOKEN_PATH):
        log.warning("Skipping Workspace automation for %s: no %s. Run "
                    "`python ophia-data/workspace_trigger.py` once to log in.", workspace_id, TOKEN_PATH)
        finish(sm.ProvisioningStatus.SKIPPED, provisioning_errors=["Google Workspace not connected"])
        return

    ws = repo.get_workspace(workspace_id)
    try:
        result = trigger_workspace_automation(
            startup_name=ws["startup_name"],
            mentor_name=ws["mentor_name"],
            synergy_score=ws["synergy_score"],
            contact_email=contact_email,
        )
    except Exception as e:
        finish(sm.ProvisioningStatus.FAILED, provisioning_errors=[str(e)])
        return

    finish(
        sm.provisioning_outcome(result.get("email_sent"), result.get("drive_folder_url"),
                                result.get("calendar_event_id")),
        intro_email_sent=bool(result.get("email_sent")),
        drive_folder_url=result.get("drive_folder_url") or ws.get("drive_folder_url"),
        calendar_event_id=result.get("calendar_event_id") or ws.get("calendar_event_id"),
        provisioning_errors=result.get("errors", []),
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", "8000")))
