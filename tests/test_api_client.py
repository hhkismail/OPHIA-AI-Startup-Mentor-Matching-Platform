"""Frontend API client: response mapping, HTML escaping, failure handling."""

import pytest
import requests

import api_client


class FakeResponse:
    def __init__(self, data, status=200):
        self.data, self.status = data, status

    def raise_for_status(self):
        if self.status >= 400:
            raise requests.HTTPError(f"{self.status} error", response=self)

    def json(self):
        return self.data

    @property
    def text(self):
        return str(self.data)


@pytest.fixture
def api(monkeypatch):
    """Points the client at a fake backend; returns a dict of path -> response data."""
    routes, sent = {}, []

    def fake_request(method, url, **kw):
        path = url.removeprefix("http://backend")
        sent.append((method, path, kw.get("json")))
        if path not in routes:
            raise requests.ConnectionError("connection refused")
        return FakeResponse(routes[path])

    monkeypatch.setattr(api_client, "API_URL", "http://backend")
    monkeypatch.setattr(requests, "request", fake_request)
    routes["sent"] = sent
    return routes


LINKAGE = {"startup_name": "Evil <script>", "mentor_name": "Dr Bio", "synergy": 88,
           "insight": "<img src=x onerror=alert(1)>", "tags": ["<b>"], "similarity": 0.6,
           "similarity_percentile": 0.97, "grades": {"domain_fit": 5, "need_fit": 4, "market_fit": 3},
           "startup_description": "d", "startup_batch": "W21", "startup_country": "US",
           "mentor_title": "VP"}


def test_disabled_when_no_url(monkeypatch):
    monkeypatch.setattr(api_client, "API_URL", "")
    assert not api_client.enabled()
    assert api_client.fetch_pending_matches() is None


def test_unreachable_backend_returns_none_and_records_error(api):
    assert api_client.fetch_workspaces() is None
    assert "connection refused" in api_client.last_error


def test_matches_are_html_escaped(api):
    api["/api/linkages"] = [LINKAGE]
    [m] = api_client.fetch_pending_matches()
    assert m["startup"] == "Evil &lt;script&gt;"
    assert "<img" not in m["insight"] and "&lt;img" in m["insight"]
    assert m["tags"] == ["&lt;b&gt;"]
    # Raw names are kept for sending back to the API
    assert m["startup_raw"] == "Evil <script>"


def test_score_detail_shows_grades_and_percentile(api):
    api["/api/linkages"] = [LINKAGE]
    [m] = api_client.fetch_pending_matches()
    assert m["score_detail"] == "Domain 5/5 · Need 4/5 · Market 3/5 · Closer than 97% of pairs"


def test_score_detail_when_ai_review_failed(api):
    api["/api/linkages"] = [{**LINKAGE, "grades": None}]
    [m] = api_client.fetch_pending_matches()
    assert m["score_detail"].startswith("AI review unavailable")


def test_workspace_mapping_reports_real_status(api):
    api["/api/workspaces"] = [{"doc_id": "e1", "workspace_name": "P", "startup_name": "S",
                               "mentor_name": "M", "status": "In Progress", "synergy_score": 90,
                               "lifecycle_start": "2026-01-01T00:00:00+00:00",
                               "lifecycle_end": "2026-04-01T00:00:00+00:00",
                               "milestones": [{"day": 30, "objective": "o", "completed": False}]}]
    [w] = api_client.fetch_workspaces()
    assert w["drive_url"] == "Not created yet"
    assert w["email_status"] == "Not sent yet"
    assert w["day"] > 0 and w["lifecycle_end"] == "01 Apr 2026"


def test_approve_sends_raw_names_and_returns_new_workspaces(api):
    api["/api/linkages"] = [LINKAGE]
    api["/api/linkages/approve"] = {"provisioned_entities": [{"entity_id": "e2"}]}
    api["/api/workspaces"] = [
        {"doc_id": d, "workspace_name": d, "startup_name": "S", "mentor_name": "M",
         "status": "In Progress", "synergy_score": 1, "lifecycle_start": "2026-01-01T00:00:00+00:00",
         "lifecycle_end": "2026-04-01T00:00:00+00:00"} for d in ("e1", "e2")]
    [m] = api_client.fetch_pending_matches()

    new = api_client.approve([m])

    assert [w["doc_id"] for w in new] == ["e2"]
    method, path, body = api["sent"][-2]
    assert (method, path) == ("POST", "/api/linkages/approve")
    assert body == [{"startup_name": "Evil <script>", "mentor_name": "Dr Bio", "synergy": 88}]


def test_mentor_mapping(api):
    api["/api/mentors"] = [{"name": "A", "title": "T", "bio": "B", "skills": ["X"],
                            "status": "Available", "availability_hours": 6}]
    [m] = api_client.fetch_mentors()
    assert m["expertise"] == ["X"] and m["partnerships"] == 0 and m["country"] == ""
