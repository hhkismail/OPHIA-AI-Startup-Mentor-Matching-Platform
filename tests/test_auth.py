"""Admin key: required for every change and for spending Gemini calls; reads stay public."""

import pytest
from fastapi.testclient import TestClient

import ai_engine
import app as backend
from conftest import ADMIN_HEADERS
from repository import InMemoryRepository

WRITE_ENDPOINTS = [
    "/api/matches/bioco__dr-bio/approve",
    "/api/matches/bioco__dr-bio/reject",
    "/api/workspaces/w1/milestones/30/complete",
    "/api/workspaces/w1/cancel",
    "/api/workspaces/w1/provision",
]
READ_ENDPOINTS = ["/api/startups", "/api/mentors", "/api/stats", "/api/workspaces",
                  "/api/matches", "/api/linkages", "/api/health"]


@pytest.fixture
def repo(startups, mentors):
    repo = InMemoryRepository(startups, mentors)
    backend.app.dependency_overrides[backend.get_repo] = lambda: repo
    yield repo
    backend.app.dependency_overrides.clear()


@pytest.fixture
def gemini_calls(monkeypatch):
    calls = []

    def grade(startup, mentor):
        calls.append(1)
        return {"reasoning": "r", "domain_fit": 4, "need_fit": 4, "market_fit": 4, "insight": "i", "tags": []}

    monkeypatch.setattr(ai_engine, "grade_pair", grade)
    return calls


anon = TestClient(backend.app)


@pytest.mark.parametrize("path", WRITE_ENDPOINTS)
def test_writes_rejected_without_key(repo, path):
    r = anon.post(path)
    assert r.status_code == 401
    assert r.headers["WWW-Authenticate"] == "ApiKey"


@pytest.mark.parametrize("path", WRITE_ENDPOINTS)
def test_writes_rejected_with_wrong_key(repo, path):
    assert anon.post(path, headers={"X-API-Key": "test-admin-kez"}).status_code == 401


@pytest.mark.parametrize("path", WRITE_ENDPOINTS)
def test_writes_disabled_when_server_has_no_key(monkeypatch, repo, path):
    # Fail closed: an unset key must not mean "no auth"
    monkeypatch.delenv("ADMIN_API_KEY")
    r = anon.post(path, headers={"X-API-Key": ""})
    assert r.status_code == 503 and "no ADMIN_API_KEY" in r.json()["detail"]


def test_empty_key_never_matches(monkeypatch, repo):
    monkeypatch.setenv("ADMIN_API_KEY", "")
    assert anon.post(WRITE_ENDPOINTS[0], headers={"X-API-Key": ""}).status_code == 503


def test_correct_key_reaches_the_endpoint(repo):
    # 404 (unknown match) proves auth passed and the handler ran
    assert anon.post(WRITE_ENDPOINTS[0], headers=ADMIN_HEADERS).status_code == 404


@pytest.mark.parametrize("path", READ_ENDPOINTS)
def test_reads_are_public(repo, gemini_calls, path):
    assert anon.get(path).status_code == 200


def test_anonymous_visitors_cannot_trigger_gemini(repo, gemini_calls):
    assert anon.get("/api/linkages?limit=3").json() == []
    assert gemini_calls == []


def test_no_server_key_means_nobody_is_admin(monkeypatch, repo, gemini_calls):
    # Fail closed on the read path too: an unset key must not make everyone admin
    monkeypatch.delenv("ADMIN_API_KEY")
    assert backend.is_admin(None) is False and backend.is_admin("") is False
    assert anon.get("/api/linkages?limit=3").json() == []
    assert gemini_calls == []


def test_anonymous_visitors_see_stored_suggestions(repo, gemini_calls):
    admin = TestClient(backend.app, headers=ADMIN_HEADERS)
    created = admin.get("/api/linkages?limit=2").json()
    assert len(created) == 2 and gemini_calls
    assert anon.get("/api/linkages?limit=2").json() == created


def test_anonymous_refresh_is_rejected(repo, gemini_calls):
    assert anon.get("/api/linkages?refresh=true").status_code == 401


@pytest.mark.parametrize("limit", [0, 51, -1])
def test_linkage_limit_is_bounded(repo, limit):
    # Caps how many Gemini calls one admin request can make
    assert anon.get(f"/api/linkages?limit={limit}").status_code == 422


def test_docs_advertise_the_api_key():
    schema = backend.app.openapi()
    assert schema["components"]["securitySchemes"]["APIKeyHeader"]["name"] == "X-API-Key"


def test_frontend_client_sends_the_key(monkeypatch):
    import requests
    import api_client
    sent = {}
    monkeypatch.setattr(api_client, "API_URL", "http://backend")
    monkeypatch.setattr(api_client, "API_KEY", "k123")

    class R:
        def raise_for_status(self): pass
        def json(self): return {}

    monkeypatch.setattr(requests, "request", lambda m, u, **kw: (sent.update(kw), R())[1])
    api_client.reject({"key": "x"})
    assert sent["headers"] == {"X-API-Key": "k123"}
