"""Streamlit dashboard, driven headlessly with streamlit.testing."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import api_client

APP = str(Path(__file__).resolve().parent.parent / "ophia-frontend" / "app.py")


def page_text(at) -> str:
    return "\n".join(str(el.value) for el in [*at.markdown, *at.caption, *at.warning, *at.error])


def start(**kw) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    assert not at.exception, at.exception
    return at


def test_demo_mode_renders_with_honest_labels():
    at = start()
    text = page_text(at)
    assert at.session_state.data_source == "mock"
    assert "Demo data" in text and "nothing is saved" in text
    # Removed fake content must stay removed
    for fake in ("124", "feedback loop", "Admin: Vaza", "Sign in", "ops@ophia.ai", "Semantic overlap"):
        assert fake not in text, fake


def test_demo_counts_come_from_the_data():
    at = start()
    from mock_data import MENTORS, PENDING_MATCHES, INITIAL_WORKSPACES
    stats = at.session_state.stats
    assert stats["startups"] == len({m["startup"] for m in PENDING_MATCHES} |
                                    {w["startup"] for w in INITIAL_WORKSPACES})
    assert stats["mentors"] == sum(m["status"] == "Available" for m in MENTORS)


def test_demo_approve_moves_match_to_workspaces_without_pretending():
    at = start()
    pending, workspaces = len(at.session_state.pending_matches), len(at.session_state.workspaces)
    at.checkbox[0].check().run()
    at.button(key="approve_btn").click().run()
    assert not at.exception
    assert len(at.session_state.pending_matches) == pending - 1
    assert len(at.session_state.workspaces) == workspaces + 1
    assert "Demo mode — no email sent" in page_text(at)


def test_approve_with_nothing_selected_warns():
    at = start()
    at.button(key="approve_btn").click().run()
    assert "select at least one match" in page_text(at)


def test_reject_removes_match():
    at = start()
    first = at.session_state.pending_matches[0]["key"]
    at.button(key=f"reject_{first}").click().run()
    assert first not in [m["key"] for m in at.session_state.pending_matches]


def test_mentors_page_search():
    at = start()
    at.session_state.page = "mentors"
    at.run()
    at.text_input(key="mentor_search").input("climate").run()
    text = page_text(at)
    assert "Sarah Chen" in text and "Ehtisham Raza" not in text


def test_contact_page_is_gone():
    at = start()
    assert "nav_contact" not in [b.key for b in at.button]


@pytest.fixture
def live_backend(monkeypatch):
    """Fake backend for live mode (patched at the requests layer the app uses)."""
    import requests

    data = {
        "/api/linkages": [{"match_id": "bioco__dr-bio", "startup_name": "BioCo", "mentor_name": "Dr Bio", "synergy": 93,
                           "insight": "Fits. Helps.", "tags": ["Biotech"], "similarity": 0.6,
                           "similarity_percentile": 0.98,
                           "grades": {"domain_fit": 5, "need_fit": 4, "market_fit": 5},
                           "startup_description": "d", "startup_batch": "W21",
                           "startup_country": "US", "mentor_title": "VP"}],
        "/api/workspaces": [],
        "/api/mentors": [{"name": "Dr Bio", "title": "VP", "bio": "b", "skills": ["Bio"],
                          "status": "Available", "availability_hours": 5}],
        "/api/stats": {"startups": 50, "mentors": 61},
    }
    workspace = {"doc_id": "w1", "workspace_name": "Project BioCo × Dr Bio", "startup_name": "BioCo",
                 "mentor_name": "Dr Bio", "status": "active", "synergy_score": 93,
                 "provisioning_status": "queued", "lifecycle_start": "2026-01-01T00:00:00+00:00",
                 "lifecycle_end": "2026-04-01T00:00:00+00:00",
                 "milestones": [{"day": d, "objective": "o", "completed": False} for d in (30, 60, 90)]}
    calls = []

    def handle(method, path, body):
        calls.append((method, path))
        if path == "/api/matches/bioco__dr-bio/approve":
            data["/api/workspaces"] = [workspace]
            return {"workspace": workspace, "created": True}
        if path == "/api/matches/bioco__dr-bio/reject":
            return {"status": "rejected"}
        if path == "/api/workspaces/w1/milestones/30/complete":
            workspace["milestones"][0]["completed"] = True
            return workspace
        return data[path]

    class R:
        def __init__(self, d): self.d = d
        def raise_for_status(self): pass
        def json(self): return self.d

    monkeypatch.setattr(api_client, "API_URL", "http://backend")
    monkeypatch.setattr(api_client, "API_KEY", "k")  # admin unless a test removes it
    monkeypatch.setattr(requests, "request",
                        lambda method, url, **kw: R(handle(method, url.removeprefix("http://backend"), kw.get("json"))))
    return calls


def test_live_mode_shows_backend_data(live_backend):
    at = start()
    text = page_text(at)
    assert at.session_state.data_source == "live"
    assert "Live data" in text and "50" in text and "61" in text
    assert "Domain 5/5 · Need 4/5 · Market 5/5 · Closer than 98% of pairs" in text


def test_unreachable_backend_falls_back_to_demo_with_warning(monkeypatch):
    monkeypatch.setattr(api_client, "API_URL", "http://127.0.0.1:9")
    at = start()
    assert at.session_state.data_source == "mock"
    assert "Backend unreachable" in page_text(at)


def test_live_approve_then_complete_milestone(live_backend):
    at = start()
    at.checkbox[0].check().run()
    at.button(key="approve_btn").click().run()
    assert not at.exception
    assert ("POST", "/api/matches/bioco__dr-bio/approve") in live_backend
    assert at.session_state.pending_matches == []
    [ws] = at.session_state.workspaces
    assert ws["email_status"] == "In progress…"

    at.button(key="ms_w1_30").click().run()
    assert ("POST", "/api/workspaces/w1/milestones/30/complete") in live_backend
    assert at.session_state.workspaces[0]["milestones"][0]["done"] is True


def test_live_reject_is_sent_to_backend(live_backend):
    at = start()
    at.button(key="reject_bioco__dr-bio").click().run()
    assert ("POST", "/api/matches/bioco__dr-bio/reject") in live_backend
    assert at.session_state.pending_matches == []


def test_demo_milestones_complete_in_order():
    at = start()
    ws = at.session_state.workspaces[1]            # day-60 done, day-90 next
    at.button(key=f"ms_{ws['doc_id']}_90").click().run()
    assert at.session_state.workspaces[1]["status"] == "Completed"


def test_live_without_key_is_read_only(live_backend, monkeypatch):
    monkeypatch.setattr(api_client, "API_KEY", "")
    at = start()
    assert "Read-only" in page_text(at)
    assert at.button(key="approve_btn").disabled
    assert at.button(key="reject_bioco__dr-bio").disabled


def test_live_with_key_can_edit(live_backend, monkeypatch):
    monkeypatch.setattr(api_client, "API_KEY", "k")
    at = start()
    assert "Read-only" not in page_text(at)
    assert not at.button(key="approve_btn").disabled
