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


LINKAGE = {"match_id": "evil-script__dr-bio", "startup_name": "Evil <script>", "mentor_name": "Dr Bio", "synergy": 88,
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
    assert m["key"] == "evil-script__dr-bio"


def test_score_detail_shows_grades_and_percentile(api):
    api["/api/linkages"] = [LINKAGE]
    [m] = api_client.fetch_pending_matches()
    assert m["score_detail"] == "Domain 5/5 · Need 4/5 · Market 3/5 · Closer than 97% of pairs"


def test_score_detail_when_ai_review_failed(api):
    api["/api/linkages"] = [{**LINKAGE, "grades": None}]
    [m] = api_client.fetch_pending_matches()
    assert m["score_detail"].startswith("AI review unavailable")


WORKSPACE = {"doc_id": "e1", "workspace_name": "P", "startup_name": "S", "mentor_name": "M",
             "status": "active", "synergy_score": 90, "provisioning_status": "skipped",
             "lifecycle_start": "2026-01-01T00:00:00+00:00", "lifecycle_end": "2026-04-01T00:00:00+00:00",
             "milestones": [{"day": 30, "objective": "o", "completed": False}]}


def test_workspace_mapping_reports_provisioning_status(api):
    api["/api/workspaces"] = [WORKSPACE]
    [w] = api_client.fetch_workspaces()
    assert w["status"] == "Active"
    assert w["drive_url"] == w["email_status"] == "Skipped — Google Workspace not connected"
    assert w["day"] > 0 and w["lifecycle_end"] == "01 Apr 2026"


def test_approve_posts_each_match_and_returns_workspaces(api):
    api["/api/linkages"] = [LINKAGE]
    api["/api/matches/evil-script__dr-bio/approve"] = {"workspace": WORKSPACE, "created": True}
    [m] = api_client.fetch_pending_matches()

    [w] = api_client.approve([m])

    assert w["doc_id"] == "e1"
    assert api["sent"][-1][:2] == ("POST", "/api/matches/evil-script__dr-bio/approve")


def test_approve_reports_failure(api):
    api["/api/linkages"] = [LINKAGE]
    [m] = api_client.fetch_pending_matches()
    assert api_client.approve([m]) is None and api_client.last_error


def test_reject_posts_reason(api):
    api["/api/matches/evil-script__dr-bio/reject"] = {"status": "rejected"}
    assert api_client.reject({"key": "evil-script__dr-bio"}, reason="not relevant")
    assert api["sent"][-1] == ("POST", "/api/matches/evil-script__dr-bio/reject", {"reason": "not relevant"})


def test_complete_milestone(api):
    done = {**WORKSPACE, "milestones": [{"day": 30, "objective": "o", "completed": True}]}
    api["/api/workspaces/e1/milestones/30/complete"] = done
    assert api_client.complete_milestone("e1", 30)["milestones"][0]["done"] is True


def test_mentor_mapping(api):
    api["/api/mentors"] = [{"name": "A", "title": "T", "bio": "B", "skills": ["X"],
                            "status": "Available", "availability_hours": 6}]
    [m] = api_client.fetch_mentors()
    assert m["expertise"] == ["X"] and m["partnerships"] == 0 and m["country"] == ""
