# api_client.py
# Talks to the OPHIA backend and converts its responses into the dict shapes
# the UI (and mock_data.py) already use. Every function returns None when the
# backend is not configured or not reachable, so the caller can fall back to
# mock data.

import html
import os
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

API_URL = os.getenv("OPHIA_API_URL", "").rstrip("/")
# Generating matches calls Gemini once per startup, so allow plenty of time
TIMEOUT = 120

last_error = None


def enabled() -> bool:
    return bool(API_URL)


def _request(method: str, path: str, **kwargs):
    global last_error
    if not enabled():
        return None
    try:
        resp = requests.request(method, f"{API_URL}{path}", timeout=TIMEOUT, **kwargs)
        resp.raise_for_status()
        last_error = None
        return resp.json()
    except requests.RequestException as e:
        detail = getattr(e.response, "text", "") if getattr(e, "response", None) is not None else ""
        last_error = f"{e} {detail}".strip()
        print(f"[api_client] {method} {path} failed: {last_error}")
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


def _to_match(item: dict, i: int) -> dict:
    return {
        "key": f"live_match_{i}_{item['startup_name']}",
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
        # Raw names for sending back to the API on approve
        "startup_raw": item["startup_name"],
        "mentor_raw": item["mentor_name"],
    }


def _to_workspace(e: dict) -> dict:
    try:
        start = datetime.fromisoformat(e["lifecycle_start"])
        day = max(0, (datetime.now(timezone.utc) - start).days)
    except (KeyError, TypeError, ValueError):
        day = 0
    return {
        "doc_id": e.get("doc_id"),
        "name": _esc(e.get("workspace_name")),
        "startup": _esc(e.get("startup_name")),
        "mentor": _esc(e.get("mentor_name")),
        "status": _esc(e.get("status")),
        "day": day,
        "synergy": int(e.get("synergy_score", 0)),
        "drive_url": _esc(e.get("drive_folder_url") or "Not created yet"),
        "calendar_id": _esc(e.get("calendar_event_id") or "Not scheduled yet"),
        "created_at": _fmt_date(e.get("lifecycle_start"), with_time=True),
        "lifecycle_end": _fmt_date(e.get("lifecycle_end")),
        "email_status": "Intro email sent" if e.get("intro_email_sent") else "Not sent yet",
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


def fetch_pending_matches(limit: int = 5):
    data = _request("GET", "/api/linkages", params={"limit": limit})
    return None if data is None else [_to_match(item, i) for i, item in enumerate(data)]


def fetch_workspaces():
    data = _request("GET", "/api/workspaces")
    return None if data is None else [_to_workspace(e) for e in data]


def approve(matches: list):
    """Approves matches; returns the newly created workspaces, or None on failure."""
    payload = [
        {"startup_name": m["startup_raw"], "mentor_name": m["mentor_raw"], "synergy": m["synergy"]}
        for m in matches
    ]
    result = _request("POST", "/api/linkages/approve", json=payload)
    if result is None:
        return None
    new_ids = {e["entity_id"] for e in result["provisioned_entities"]}
    workspaces = fetch_workspaces() or []
    return [w for w in workspaces if w["doc_id"] in new_ids]
