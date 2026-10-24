"""FastAPI backend on an InMemoryRepository, with Gemini replaced by a fake grader."""

import threading

import pytest
from fastapi.testclient import TestClient

import ai_engine
import app as backend
from repository import InMemoryRepository


@pytest.fixture
def repo(startups, mentors):
    repo = InMemoryRepository(startups, mentors)
    backend.app.dependency_overrides[backend.get_repo] = lambda: repo
    yield repo
    backend.app.dependency_overrides.clear()


@pytest.fixture
def gemini(monkeypatch):
    """Fake grader: 5/5/5 for each startup's domain mentor, 2/2/2 otherwise."""
    calls = []
    best = {"BioCo": "Dr Bio", "PayCo": "Ms Pay", "FarmCo": "Mr Farm"}

    def grade(startup, mentor):
        calls.append((startup["company_name"], mentor["name"]))
        g = 5 if best[startup["company_name"]] == mentor["name"] else 2
        return {"reasoning": "r", "domain_fit": g, "need_fit": g, "market_fit": g,
                "insight": "Fits. Helps.", "tags": ["T"]}

    monkeypatch.setattr(ai_engine, "grade_pair", grade)
    return calls


@pytest.fixture
def provisioned(monkeypatch):
    calls = []
    monkeypatch.setattr(backend, "_provision_workspace", lambda repo, ws_id, email: calls.append(ws_id))
    return calls


@pytest.fixture
def client():
    return TestClient(backend.app)


def pending(client, limit=3):
    return {m["startup_name"]: m for m in client.get(f"/api/linkages?limit={limit}").json()}


# ── Errors ───────────────────────────────────────────────────────────────────

def test_health_reports_firestore_down(client):
    body = client.get("/api/health").json()
    assert body["firestore"] is False and body["status"] == "degraded"


def test_endpoints_return_503_when_firestore_is_down(client):
    # No repo override: the real FirestoreRepository hits the blocked network
    for path in ("/api/linkages", "/api/startups", "/api/mentors", "/api/workspaces", "/api/stats"):
        r = client.get(path)
        assert r.status_code == 503, path
        assert "Firestore unavailable" in r.json()["detail"]


def test_unknown_ids_are_404(client, repo):
    assert client.post("/api/matches/nope/approve").status_code == 404
    assert client.post("/api/matches/nope/reject").status_code == 404
    assert client.post("/api/workspaces/nope/cancel").status_code == 404


# ── Suggestions ──────────────────────────────────────────────────────────────

def test_linkages_suggest_best_mentor_per_startup(client, repo, gemini):
    picks = {s: m["mentor_name"] for s, m in pending(client).items()}
    assert picks == {"BioCo": "Dr Bio", "PayCo": "Ms Pay", "FarmCo": "Mr Farm"}
    m = pending(client)["BioCo"]
    assert m["status"] == "pending" and m["match_id"] == "bioco__dr-bio"
    assert m["grades"] and m["mentor_title"] and "similarity_percentile" in m


def test_linkages_respect_limit(client, repo, gemini):
    assert len(client.get("/api/linkages?limit=2").json()) == 2


def test_suggestions_are_stored_not_regenerated(client, repo, gemini):
    pending(client)
    n = len(gemini)
    pending(client)
    assert len(gemini) == n
    assert len(repo.matches("pending")) == 3


def test_refresh_regenerates_pending_only(client, repo, gemini, provisioned):
    pending(client)
    assert client.post("/api/matches/bioco__dr-bio/approve").status_code == 200
    n = len(gemini)
    client.get("/api/linkages?limit=3&refresh=true")
    assert len(gemini) > n
    assert repo.matches("approved")[0]["match_id"] == "bioco__dr-bio"  # decisions survive refresh


# ── Approve / reject ─────────────────────────────────────────────────────────

def test_approve_creates_workspace_and_queues_provisioning(client, repo, gemini, provisioned):
    pending(client)
    r = client.post("/api/matches/bioco__dr-bio/approve")
    assert r.status_code == 200 and r.json()["created"] is True
    ws = r.json()["workspace"]
    assert ws["status"] == "active" and ws["provisioning_status"] == "queued"
    assert ws["match_id"] == "bioco__dr-bio" and len(ws["milestones"]) == 3
    assert provisioned == [ws["doc_id"]]


def test_approve_is_idempotent(client, repo, gemini, provisioned):
    # Regression: double-clicking Approve created two workspaces
    pending(client)
    first = client.post("/api/matches/bioco__dr-bio/approve").json()
    second = client.post("/api/matches/bioco__dr-bio/approve").json()
    assert second["created"] is False
    assert second["workspace"]["doc_id"] == first["workspace"]["doc_id"]
    assert len(repo.workspaces()) == 1 and len(provisioned) == 1


def test_concurrent_approvals_create_one_workspace(monkeypatch, client, repo, gemini, provisioned):
    pending(client)
    # Widen the read-check-write window so a missing lock reliably shows up
    import time
    import repository
    real = repository.new_workspace
    monkeypatch.setattr(repository, "new_workspace", lambda m: (time.sleep(0.02), real(m))[1])
    results = []
    threads = [threading.Thread(target=lambda: results.append(
        client.post("/api/matches/bioco__dr-bio/approve").json())) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(r["created"] for r in results) == 1
    assert len({r["workspace"]["doc_id"] for r in results}) == 1
    assert len(repo.workspaces()) == 1


def test_approved_startup_gets_no_new_suggestions(client, repo, gemini, provisioned):
    pending(client)
    client.post("/api/matches/bioco__dr-bio/approve")
    assert "BioCo" not in pending(client)


def test_reject_is_persisted_and_mentor_never_resuggested(client, repo, gemini):
    pending(client)
    r = client.post("/api/matches/bioco__dr-bio/reject", json={"reason": "conflict of interest"})
    assert r.json()["status"] == "rejected" and r.json()["reject_reason"] == "conflict of interest"
    # Regression: rejected matches came back on reload
    nxt = pending(client)["BioCo"]
    assert nxt["mentor_name"] != "Dr Bio"


def test_reject_without_body(client, repo, gemini):
    pending(client)
    assert client.post("/api/matches/bioco__dr-bio/reject").json()["reject_reason"] is None


def test_cannot_approve_a_rejected_match(client, repo, gemini):
    pending(client)
    client.post("/api/matches/bioco__dr-bio/reject")
    r = client.post("/api/matches/bioco__dr-bio/approve")
    assert r.status_code == 409 and "from 'rejected' to 'approved'" in r.json()["detail"]


def test_cannot_reject_an_approved_match(client, repo, gemini, provisioned):
    pending(client)
    client.post("/api/matches/bioco__dr-bio/approve")
    assert client.post("/api/matches/bioco__dr-bio/reject").status_code == 409


def test_matches_endpoint_filters_by_status(client, repo, gemini, provisioned):
    pending(client)
    client.post("/api/matches/bioco__dr-bio/approve")
    client.post("/api/matches/payco__ms-pay/reject")
    assert [m["match_id"] for m in client.get("/api/matches?status=approved").json()] == ["bioco__dr-bio"]
    assert [m["match_id"] for m in client.get("/api/matches?status=rejected").json()] == ["payco__ms-pay"]
    assert client.get("/api/matches?status=bogus").status_code == 422


# ── Workspaces ───────────────────────────────────────────────────────────────

@pytest.fixture
def workspace_id(client, repo, gemini, provisioned):
    pending(client)
    return client.post("/api/matches/bioco__dr-bio/approve").json()["workspace"]["doc_id"]


def test_milestones_complete_in_order_then_workspace_completes(client, workspace_id):
    url = f"/api/workspaces/{workspace_id}/milestones"
    assert client.post(f"{url}/60/complete").status_code == 409
    assert client.post(f"{url}/30/complete").json()["status"] == "active"
    client.post(f"{url}/60/complete")
    final = client.post(f"{url}/90/complete").json()
    assert final["status"] == "completed" and final["active"] is False
    assert client.post(f"/api/workspaces/{workspace_id}/cancel").status_code == 409


def test_cancel_freezes_milestones(client, workspace_id):
    assert client.post(f"/api/workspaces/{workspace_id}/cancel").json()["status"] == "cancelled"
    assert client.post(f"/api/workspaces/{workspace_id}/milestones/30/complete").status_code == 409


# ── Provisioning (the background task itself) ────────────────────────────────

@pytest.fixture
def ws_in_repo(repo):
    repo.add_matches([{"match_id": "m1", "startup_name": "BioCo", "mentor_name": "Dr Bio",
                       "synergy": 90, "status": "pending", "created_at": "t"}])
    ws, _ = repo.approve_match("m1")
    return ws["doc_id"]


@pytest.fixture
def google_logged_in(monkeypatch, tmp_path):
    import workspace_trigger
    token = tmp_path / "token.json"
    token.write_text("{}")
    monkeypatch.setattr(workspace_trigger, "TOKEN_PATH", str(token))
    return workspace_trigger


def test_provisioning_skipped_without_google_login(monkeypatch, tmp_path, repo, ws_in_repo):
    import workspace_trigger
    monkeypatch.setattr(workspace_trigger, "TOKEN_PATH", str(tmp_path / "missing.json"))
    monkeypatch.setattr(workspace_trigger, "trigger_workspace_automation",
                        lambda **kw: pytest.fail("must not run without a token"))
    backend._provision_workspace(repo, ws_in_repo, None)
    ws = repo.get_workspace(ws_in_repo)
    assert ws["provisioning_status"] == "skipped"
    assert ws["provisioning_errors"] == ["Google Workspace not connected"]


def test_provisioning_success_records_results(monkeypatch, repo, ws_in_repo, google_logged_in):
    monkeypatch.setattr(google_logged_in, "trigger_workspace_automation", lambda **kw: {
        "email_sent": True, "drive_folder_url": "https://drive/x", "calendar_event_id": "ev", "errors": []})
    backend._provision_workspace(repo, ws_in_repo, "founder@example.com")
    ws = repo.get_workspace(ws_in_repo)
    assert ws["provisioning_status"] == "succeeded"
    assert ws["drive_folder_url"] == "https://drive/x" and ws["intro_email_sent"] is True


def test_provisioning_partial_then_retry(monkeypatch, client, repo, ws_in_repo, google_logged_in):
    monkeypatch.setattr(google_logged_in, "trigger_workspace_automation", lambda **kw: {
        "email_sent": True, "drive_folder_url": None, "calendar_event_id": "ev",
        "errors": ["Drive folder failed (see server log)"]})
    backend._provision_workspace(repo, ws_in_repo, None)
    assert repo.get_workspace(ws_in_repo)["provisioning_status"] == "partial"

    # Retry endpoint re-queues and runs the task again
    retried = []
    monkeypatch.setattr(backend, "_provision_workspace", lambda r, ws_id, email: retried.append(ws_id))
    r = client.post(f"/api/workspaces/{ws_in_repo}/provision")
    assert r.json()["provisioning_status"] == "queued" and retried == [ws_in_repo]


def test_provisioning_crash_is_recorded_as_failed(monkeypatch, repo, ws_in_repo, google_logged_in):
    def boom(**kw):
        raise RuntimeError("token revoked")
    monkeypatch.setattr(google_logged_in, "trigger_workspace_automation", boom)
    backend._provision_workspace(repo, ws_in_repo, None)
    ws = repo.get_workspace(ws_in_repo)
    assert ws["provisioning_status"] == "failed" and ws["provisioning_errors"] == ["token revoked"]


def test_cannot_retry_succeeded_provisioning(monkeypatch, client, repo, ws_in_repo, google_logged_in):
    monkeypatch.setattr(google_logged_in, "trigger_workspace_automation", lambda **kw: {
        "email_sent": True, "drive_folder_url": "u", "calendar_event_id": "e", "errors": []})
    backend._provision_workspace(repo, ws_in_repo, None)
    assert client.post(f"/api/workspaces/{ws_in_repo}/provision").status_code == 409


# ── Misc ─────────────────────────────────────────────────────────────────────

def test_mentors_and_startups_hide_embeddings(client, repo):
    for path in ("/api/mentors", "/api/startups"):
        body = client.get(path).json()
        assert body and not any(k.endswith("_embedding") for row in body for k in row)


def test_stats(client, repo):
    assert client.get("/api/stats").json() == {"startups": 3, "mentors": 4}


def test_legacy_workspaces_are_normalized():
    repo = InMemoryRepository()
    repo._workspaces["old"] = {"doc_id": "old", "status": "In Progress", "drive_folder_url": "u",
                               "milestones": []}
    ws = repo.get_workspace("old")
    assert ws["status"] == "active" and ws["provisioning_status"] == "succeeded"
