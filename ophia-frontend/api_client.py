# api_client.py
# Talks to the OPHIA backend and converts its responses into the dict shapes
# the UI (and mock_data.py) already use. Every function returns None when the
# backend is not configured or not reachable, so the caller can fall back to
# mock data.

import logging
import html
import os
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

log = logging.getLogger(__name__)

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

API_URL = os.getenv("OPHIA_API_URL", "").rstrip("/")
# Admin key for approve/reject/milestones and for generating new suggestions.
# Streamlit runs this on the server, so the key never reaches the browser.
API_KEY = os.getenv("OPHIA_API_KEY", "")
# The first batch of suggestions grades every startup with Gemini, so allow plenty of time
TIMEOUT = 300
# Pending suggestions loaded per session (the backend caps it at 50)
PENDING_LIMIT = min(max(int(os.getenv("OPHIA_PENDING_LIMIT", "5")), 1), 50)

last_error = None


def enabled() -> bool:
    return bool(API_URL)


def _request(method: str, path: str, **kwargs):
    global last_error
    if not enabled():
        return None
    headers = {"X-API-Key": API_KEY} if API_KEY else {}
    try:
        resp = requests.request(method, f"{API_URL}{path}", timeout=TIMEOUT, headers=headers, **kwargs)
        resp.raise_for_status()
        last_error = None
        return resp.json()
    except requests.RequestException as e:
        detail = getattr(e.response, "text", "") if getattr(e, "response", None) is not None else ""
        last_error = f"{e} {detail}".strip()
        log.warning(f"{method} {path} failed: {last_error}")
        return None


def _esc(value) -> str:
    # Live text (incl. Gemini output) is rendered with unsafe_allow_html
    return html.escape(str(value or ""))


def _fmt_date(iso: str, with_time: bool = False) -> str:
    try:
        dt = datetime.fromisoformat(iso)
        return dt.strftime("%d %b %Y, %H:%M UTC" if with_time else "%d %b %Y")
    except (TypeError, ValueError):
        return ""


def _score_detail(item: dict) -> str:
    """'Domain 5/5 · Need 4/5 · Market 3/5 · Closer than 97% of pairs'"""
    parts = []
    grades = item.get("grades")
    if grades:
        parts += [f"{label} {grades[key]}/5" for label, key in
                  (("Domain", "domain_fit"), ("Need", "need_fit"), ("Market", "market_fit"))]
    else:
        parts.append("AI review unavailable")
    if item.get("similarity_percentile") is not None:
        parts.append(f"Closer than {round(100 * item['similarity_percentile'])}% of pairs")
    return " · ".join(parts)


def _to_match(item: dict) -> dict:
    return {
        "key": item["match_id"],
        "startup": _esc(item["startup_name"]),
        "startup_desc": _esc(item.get("startup_description")),
        "startup_batch": _esc(item.get("startup_batch")),
        "startup_country": _esc(item.get("startup_country")),
        "mentor": _esc(item["mentor_name"]),
        "mentor_title": _esc(item.get("mentor_title")),
        "synergy": int(item.get("synergy", 0)),
        "insight": _esc(item.get("insight")),
        "tags": [_esc(t) for t in item.get("tags", [])],
        "score_detail": _esc(_score_detail(item)),
        "grades": item.get("grades"),
    }


PROVISIONING_LABELS = {
    "queued": "In progress…",
    "skipped": "Skipped — Google Workspace not connected",
    "failed": "Failed — retry from the API",
}


def _to_workspace(e: dict) -> dict:
    try:
        start = datetime.fromisoformat(e["lifecycle_start"])
        day = max(0, (datetime.now(timezone.utc) - start).days)
    except (KeyError, TypeError, ValueError):
        day = 0
    pending = PROVISIONING_LABELS.get(e.get("provisioning_status"))
    return {
        "doc_id": e.get("doc_id"),
        "name": _esc(e.get("workspace_name")),
        "startup": _esc(e.get("startup_name")),
        "mentor": _esc(e.get("mentor_name")),
        "status": _esc(str(e.get("status", "")).capitalize()),
        "day": day,
        "synergy": int(e.get("synergy_score", 0)),
        "drive_url": _esc(e.get("drive_folder_url") or pending or "Not created"),
        "calendar_id": _esc(e.get("calendar_event_id") or pending or "Not scheduled"),
        "created_at": _fmt_date(e.get("lifecycle_start"), with_time=True),
        "lifecycle_end": _fmt_date(e.get("lifecycle_end")),
        "email_status": "Intro email sent" if e.get("intro_email_sent") else (pending or "Not sent"),
        "milestones": [
            {"day": m["day"], "label": _esc(m["objective"]), "done": m["completed"]}
            for m in e.get("milestones", [])
        ],
    }


def _to_mentor(m: dict) -> dict:
    return {
        "name": _esc(m.get("name")),
        "title": _esc(m.get("title")),
        "bio": _esc(m.get("bio")),
        "expertise": [_esc(s) for s in (m.get("skills") or m.get("industry_tags") or [])],
        "status": _esc(m.get("status", "Available")),
        "partnerships": int(m.get("partnerships", 0)),
        "availability_hours": int(m.get("availability_hours", 0)),
        "country": _esc(m.get("country")),
    }


def fetch_mentors():
    data = _request("GET", "/api/mentors")
    return None if data is None else [_to_mentor(m) for m in data]


def fetch_stats():
    """{'startups': int, 'mentors': int} — counts for the dashboard header."""
    return _request("GET", "/api/stats")


def fetch_pending_matches(limit: int = PENDING_LIMIT):
    data = _request("GET", "/api/linkages", params={"limit": limit})
    return None if data is None else [_to_match(item) for item in data]


def fetch_workspaces():
    data = _request("GET", "/api/workspaces")
    return None if data is None else [_to_workspace(e) for e in data]


def approve(matches: list):
    """Approves each match; returns their workspaces (existing ones for matches
    approved before), or None if any approval failed (see last_error)."""
    workspaces = []
    for m in matches:
        result = _request("POST", f"/api/matches/{m['key']}/approve")
        if result is None:
            return None
        workspaces.append(_to_workspace(result["workspace"]))
    return workspaces


def reject(match: dict, reason: str | None = None) -> bool:
    return _request("POST", f"/api/matches/{match['key']}/reject", json={"reason": reason}) is not None


def complete_milestone(workspace_id: str, day: int):
    """Marks a milestone done; returns the updated workspace or None (see last_error)."""
    data = _request("POST", f"/api/workspaces/{workspace_id}/milestones/{day}/complete")
    return None if data is None else _to_workspace(data)


# ── Snapshot (public demo) ───────────────────────────────────────────────────
# export_snapshot.py saves real API responses to snapshot.json; the public demo
# renders them through the same mapping functions as live mode, read-only.

SNAPSHOT_PATH = Path(os.getenv("OPHIA_SNAPSHOT_PATH", Path(__file__).resolve().parent / "snapshot.json"))


def load_snapshot() -> dict | None:
    """The snapshot mapped into UI shapes, or None if there is no snapshot file."""
    import json
    if not SNAPSHOT_PATH.exists():
        return None
    raw = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    return {
        "exported_at": _fmt_date(raw.get("exported_at")),
        "pending_matches": [_to_match(m) for m in raw["linkages"]],
        "workspaces": [_to_workspace(w) for w in raw["workspaces"]],
        "mentors": [_to_mentor(m) for m in raw["mentors"]],
        "stats": raw["stats"],
    }
