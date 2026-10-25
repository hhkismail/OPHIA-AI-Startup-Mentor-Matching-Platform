"""
The production FirestoreRepository against the Firestore emulator: real
transactions, real AlreadyExists, real contention. The unit tests use the
InMemoryRepository; these prove the Firestore implementation obeys the same
rules.

Skipped unless FIRESTORE_EMULATOR_HOST is set. CI runs them with:
    firebase emulators:exec --only firestore --project demo-ophia "pytest tests/integration"
"""

import os
import threading
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skipif(not os.getenv("FIRESTORE_EMULATOR_HOST"),
                                reason="needs the Firestore emulator (FIRESTORE_EMULATOR_HOST)")

PROJECT = "demo-ophia"  # "demo-" projects need no credentials on the emulator


@pytest.fixture
def db():
    import requests
    from google.cloud import firestore
    host = os.environ["FIRESTORE_EMULATOR_HOST"]
    # Wipe the emulator so every test starts empty
    requests.delete(f"http://{host}/emulator/v1/projects/{PROJECT}/databases/(default)/documents").raise_for_status()
    return firestore.Client(project=PROJECT)


@pytest.fixture
def repo(db, startups, mentors):
    from repository import FirestoreRepository
    # FirestoreRepository only needs get_db() for matches/workspaces; reads of
    # the seeded startups/mentors come from the fixtures
    shim = SimpleNamespace(get_db=lambda: db,
                           get_active_startups=lambda: startups, get_all_startups=lambda: startups,
                           get_available_mentors=lambda: mentors, get_all_mentors=lambda: mentors)
    return FirestoreRepository(shim)


def match(startup="BioCo", mentor="Dr Bio", synergy=90):
    from repository import new_match
    return new_match({"startup_name": startup, "mentor_name": mentor, "synergy": synergy,
                      "insight": "i", "tags": [], "similarity": 0.6, "similarity_percentile": 0.9})


def test_add_matches_never_overwrites_a_decision(repo):
    m = match()
    repo.add_matches([m])
    repo.approve_match(m["match_id"])
    repo.add_matches([match(synergy=10)])  # same pair suggested again
    [stored] = repo.matches()
    assert stored["status"] == "approved" and stored["synergy"] == 90


def test_approve_creates_workspace_and_is_idempotent(repo, db):
    m = match()
    repo.add_matches([m])
    ws, created = repo.approve_match(m["match_id"])
    again, created_again = repo.approve_match(m["match_id"])
    assert created and not created_again and again["doc_id"] == ws["doc_id"]
    assert len(list(db.collection("active_entities").stream())) == 1
    assert repo.matches("approved")[0]["workspace_id"] == ws["doc_id"]


def test_concurrent_approvals_create_one_workspace(repo, db):
    m = match()
    repo.add_matches([m])
    results, errors = [], []

    def approve():
        try:
            results.append(repo.approve_match(m["match_id"]))
        except Exception as e:  # pragma: no cover - would fail the assertions below
            errors.append(e)

    threads = [threading.Thread(target=approve) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors
    assert sum(created for _, created in results) == 1
    assert len({ws["doc_id"] for ws, _ in results}) == 1
    assert len(list(db.collection("active_entities").stream())) == 1


def test_lifecycle_rules_hold_inside_transactions(repo, db):
    import state_machine as sm
    m = match()
    repo.add_matches([m])
    repo.reject_match(m["match_id"], "not relevant")
    with pytest.raises(sm.InvalidTransition):
        repo.approve_match(m["match_id"])
    # The failed transaction left nothing behind
    assert list(db.collection("active_entities").stream()) == []
    assert repo.matches("rejected")[0]["reject_reason"] == "not relevant"


def test_update_workspace_persists_milestones(repo):
    import state_machine as sm
    m = match()
    repo.add_matches([m])
    ws, _ = repo.approve_match(m["match_id"])

    def complete(day):
        def change(w):
            ms, status = sm.complete_milestone(w["status"], w["milestones"], day)
            return {"milestones": ms, "status": status.value}
        return change

    for day in (30, 60, 90):
        repo.update_workspace(ws["doc_id"], complete(day))
    stored = repo.get_workspace(ws["doc_id"])
    assert stored["status"] == "completed" and all(x["completed"] for x in stored["milestones"])
    with pytest.raises(sm.InvalidTransition):
        repo.update_workspace(ws["doc_id"], complete(30))


def test_delete_pending_keeps_decisions(repo):
    a, b, c = match("A", "M1"), match("B", "M2"), match("C", "M3")
    repo.add_matches([a, b, c])
    repo.approve_match(a["match_id"])
    repo.reject_match(b["match_id"])
    assert repo.delete_pending_matches() == 1
    assert sorted(m["status"] for m in repo.matches()) == ["approved", "rejected"]


def test_unknown_ids_raise_not_found(repo):
    from repository import NotFound
    for call in (lambda: repo.approve_match("nope"), lambda: repo.reject_match("nope"),
                 lambda: repo.get_workspace("nope"), lambda: repo.update_workspace("nope", lambda w: {})):
        with pytest.raises(NotFound):
            call()


def test_legacy_workspace_documents_are_normalized(repo, db):
    db.collection("active_entities").document("old").set({
        "workspace_name": "P", "startup_name": "S", "mentor_name": "M", "synergy_score": 80,
        "status": "In Progress", "active": True, "lifecycle_start": "2026-01-01T00:00:00+00:00",
        "lifecycle_end": "2026-04-01T00:00:00+00:00", "milestones": [], "drive_folder_url": None})
    ws = repo.get_workspace("old")
    assert ws["status"] == "active" and ws["provisioning_status"] == "queued"


def test_api_end_to_end_on_firestore(repo, monkeypatch):
    """The real API, storing in the emulator: suggest, approve twice, reject, milestones."""
    from fastapi.testclient import TestClient
    import ai_engine
    import app as backend
    from conftest import ADMIN_HEADERS

    monkeypatch.setattr(ai_engine, "grade_pair", lambda s, m: {
        "reasoning": "r", "domain_fit": 5, "need_fit": 5, "market_fit": 5, "insight": "i", "tags": []})
    backend.app.dependency_overrides[backend.get_repo] = lambda: repo
    monkeypatch.setattr(backend, "_provision_workspace", lambda *a: None)
    try:
        client = TestClient(backend.app, headers=ADMIN_HEADERS)
        pending = client.get("/api/linkages?limit=3").json()
        assert len(pending) == 3
        first = pending[0]["match_id"]
        a = client.post(f"/api/matches/{first}/approve").json()
        b = client.post(f"/api/matches/{first}/approve").json()
        assert a["created"] and not b["created"] and a["workspace"]["doc_id"] == b["workspace"]["doc_id"]
        assert client.post(f"/api/matches/{first}/reject").status_code == 409
        ws = a["workspace"]["doc_id"]
        assert client.post(f"/api/workspaces/{ws}/milestones/60/complete").status_code == 409
        assert client.post(f"/api/workspaces/{ws}/milestones/30/complete").json()["milestones"][0]["completed"]
    finally:
        backend.app.dependency_overrides.clear()
