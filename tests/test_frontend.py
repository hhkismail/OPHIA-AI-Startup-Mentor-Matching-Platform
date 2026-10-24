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
        "/api/linkages": [{"startup_name": "BioCo", "mentor_name": "Dr Bio", "synergy": 93,
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

    class R:
        def __init__(self, d): self.d = d
        def raise_for_status(self): pass
        def json(self): return self.d

    monkeypatch.setattr(api_client, "API_URL", "http://backend")
    monkeypatch.setattr(requests, "request",
                        lambda method, url, **kw: R(data[url.removeprefix("http://backend")]))


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
