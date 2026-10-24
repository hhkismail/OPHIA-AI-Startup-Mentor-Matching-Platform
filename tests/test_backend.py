"""FastAPI backend, with Firestore and Gemini replaced by in-memory fakes."""

import pytest
from fastapi.testclient import TestClient

import ai_engine
import app as backend


@pytest.fixture
def fake_db(monkeypatch, startups, mentors):
    """In-memory stand-in for ophia-data/database.py."""
    db = backend.database
    entities = []

    def create(startup_name, mentor_name, synergy):
        entities.append({"doc_id": f"e{len(entities)}", "startup_name": startup_name,
                         "mentor_name": mentor_name, "synergy_score": synergy})
        return entities[-1]["doc_id"]

    monkeypatch.setattr(db, "get_db", lambda: object())
    monkeypatch.setattr(db, "get_active_startups", lambda: startups)
    monkeypatch.setattr(db, "get_all_startups", lambda: startups)
    monkeypatch.setattr(db, "get_available_mentors", lambda: mentors)
    monkeypatch.setattr(db, "get_all_mentors", lambda: mentors)
    monkeypatch.setattr(db, "get_all_active_entities", lambda: entities)
    monkeypatch.setattr(db, "create_active_entity", create)
    backend._linkage_cache.clear()
    return entities


@pytest.fixture
def gemini(monkeypatch):
    """Fake grader: 5/5/5 for the mentor whose name matches the startup's domain."""
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
    monkeypatch.setattr(backend, "_provision_workspace", lambda entity_id, req: calls.append(entity_id))
    return calls


@pytest.fixture
def client():
    return TestClient(backend.app)


def test_health_reports_firestore_down(client):
    assert client.get("/api/health").json() == {
        "status": "degraded", "firestore": False,
        "error": "network access is disabled in tests — patch in a fake"}


def test_endpoints_return_503_when_firestore_is_down(client):
    for path in ("/api/linkages", "/api/startups", "/api/mentors", "/api/workspaces", "/api/stats"):
        r = client.get(path)
        assert r.status_code == 503, path
        assert "Firestore unavailable" in r.json()["detail"]


def test_linkages_pick_best_mentor_per_startup(client, fake_db, gemini):
    r = client.get("/api/linkages?limit=3")
    assert r.status_code == 200
    picks = {x["startup_name"]: x["mentor_name"] for x in r.json()}
    assert picks == {"BioCo": "Dr Bio", "PayCo": "Ms Pay", "FarmCo": "Mr Farm"}
    first = r.json()[0]
    assert first["grades"] and first["mentor_title"] and "similarity_percentile" in first


def test_linkages_respect_limit(client, fake_db, gemini):
    assert len(client.get("/api/linkages?limit=2").json()) == 2


def test_linkages_are_cached_until_refresh(client, fake_db, gemini):
    client.get("/api/linkages?limit=1")
    n = len(gemini)
    client.get("/api/linkages?limit=1")
    assert len(gemini) == n                     # served from cache
    client.get("/api/linkages?limit=1&refresh=true")
    assert len(gemini) == 2 * n                 # recomputed


def test_refresh_clears_every_cached_limit(client, fake_db, gemini):
    # Regression: refresh used to clear only the requested limit's entry
    client.get("/api/linkages?limit=1")
    client.get("/api/linkages?limit=2&refresh=true")
    n = len(gemini)
    client.get("/api/linkages?limit=1")
    assert len(gemini) > n


def test_approve_creates_entity_and_queues_automation(client, fake_db, gemini, provisioned):
    r = client.post("/api/linkages/approve",
                    json=[{"startup_name": "BioCo", "mentor_name": "Dr Bio", "synergy": 97}])
    assert r.status_code == 200
    assert r.json()["provisioned_entities"] == [
        {"entity_id": "e0", "startup_name": "BioCo", "mentor_name": "Dr Bio"}]
    assert fake_db[0]["synergy_score"] == 97
    assert provisioned == ["e0"]


def test_approved_startups_drop_out_of_pending(client, fake_db, gemini, provisioned):
    client.get("/api/linkages?limit=3")
    client.post("/api/linkages/approve",
                json=[{"startup_name": "BioCo", "mentor_name": "Dr Bio", "synergy": 97}])
    names = [x["startup_name"] for x in client.get("/api/linkages?limit=3").json()]
    assert "BioCo" not in names


@pytest.mark.parametrize("payload", [
    [{"startup_name": "A", "mentor_name": "B", "synergy": 101}],
    [{"startup_name": "A", "mentor_name": "B", "synergy": -1}],
    [{"startup_name": "A", "synergy": 50}],
    {"startup_name": "A", "mentor_name": "B", "synergy": 50},  # not a list
])
def test_approve_validates_input(client, fake_db, payload):
    assert client.post("/api/linkages/approve", json=payload).status_code == 422


def test_mentors_and_startups_hide_embeddings(client, fake_db):
    for path in ("/api/mentors", "/api/startups"):
        body = client.get(path).json()
        assert body and not any(k.endswith("_embedding") for row in body for k in row)


def test_stats(client, fake_db):
    assert client.get("/api/stats").json() == {"startups": 3, "mentors": 4}


def test_provisioning_skips_without_google_login(monkeypatch, tmp_path, capsys):
    import workspace_trigger
    monkeypatch.setattr(workspace_trigger, "TOKEN_PATH", str(tmp_path / "missing-token.json"))
    monkeypatch.setattr(workspace_trigger, "trigger_workspace_automation",
                        lambda **kw: pytest.fail("must not run without a token"))
    req = backend.ApproveLinkageRequest(startup_name="A", mentor_name="B", synergy=50)
    backend._provision_workspace("e0", req)
    assert "Skipping Workspace automation" in capsys.readouterr().out
