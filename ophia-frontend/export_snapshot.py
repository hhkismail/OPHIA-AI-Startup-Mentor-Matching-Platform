"""
export_snapshot.py — freeze real backend output into snapshot.json.

The public demo shows this snapshot instead of calling the backend, so
visitors never touch Google Cloud (no cost, no credentials). The data is
fetched through the backend API as an anonymous user, which by design never
triggers Gemini calls — it only reads what is stored.

Run from the repo root (needs Firestore access):
    python ophia-frontend/export_snapshot.py
"""

import datetime
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_PATH = Path(__file__).resolve().parent / "snapshot.json"
ENDPOINTS = {
    "linkages": "/api/linkages?limit=50",
    "workspaces": "/api/workspaces",
    "mentors": "/api/mentors",
    "stats": "/api/stats",
}


def export(client) -> dict:
    """Fetches every endpoint the dashboard needs. `client` is a TestClient
    (or anything with .get returning a response)."""
    data = {}
    for name, path in ENDPOINTS.items():
        r = client.get(path)
        r.raise_for_status()
        data[name] = r.json()
    return {"exported_at": datetime.datetime.now(datetime.timezone.utc).isoformat(), **data}


def main():
    sys.path.insert(0, str(ROOT / "ophia-backend"))
    from fastapi.testclient import TestClient
    import app as backend

    snapshot = export(TestClient(backend.app))  # no X-API-Key: read-only, no Gemini
    SNAPSHOT_PATH.write_text(json.dumps(snapshot, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"Saved {SNAPSHOT_PATH.name}: {len(snapshot['linkages'])} matches, "
          f"{len(snapshot['workspaces'])} workspaces, {len(snapshot['mentors'])} mentors")


if __name__ == "__main__":
    main()
