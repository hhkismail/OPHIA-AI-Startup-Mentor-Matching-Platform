"""Matching pipeline: ranking, Gemini grading fallbacks, retries, client creation."""

import threading
import time

import pytest

import ai_engine as ai


def grades(d, n, m):
    return {"reasoning": "r", "domain_fit": d, "need_fit": n, "market_fit": m,
            "insight": "Two sentences. Here.", "tags": ["T"]}


def test_match_startup_ranks_by_similarity_then_grades(monkeypatch, startups, mentors):
    monkeypatch.setattr(ai, "grade_pair", lambda s, m: grades(5, 5, 5) if m["name"] == "Dr Bio" else grades(2, 2, 2))
    results = ai.match_startup(startups[0], mentors, top_n=2)

    assert [r["mentor_name"] for r in results] == ["Dr Bio", "Generalist"]
    assert results[0]["synergy"] > results[1]["synergy"]
    assert results[0]["grades"] == {"domain_fit": 5, "need_fit": 5, "market_fit": 5}
    assert set(results[0]) >= {"startup_name", "mentor_name", "synergy", "insight", "tags",
                               "similarity", "similarity_percentile"}


def test_rubric_can_reorder_embedding_ranking(monkeypatch, startups, mentors):
    # Embeddings put Dr Bio first, but the rubric says the Generalist fits better
    monkeypatch.setattr(ai, "grade_pair", lambda s, m: grades(5, 5, 5) if m["name"] == "Generalist" else grades(1, 1, 1))
    results = ai.match_startup(startups[0], mentors, top_n=2)
    assert results[0]["mentor_name"] == "Generalist"


def test_grading_failure_falls_back_to_similarity(monkeypatch, startups, mentors):
    monkeypatch.setattr(ai, "grade_pair", lambda s, m: None)
    [r] = ai.match_startup(startups[0], mentors, top_n=1)
    assert r["grades"] is None
    assert r["synergy"] == round(100 * r["similarity_percentile"])
    assert "unavailable" in r["insight"]


def test_mentors_without_embeddings_are_skipped(monkeypatch, startups, mentors):
    monkeypatch.setattr(ai, "grade_pair", lambda s, m: grades(3, 3, 3))
    mentors[0]["bio_embedding"] = None
    names = [r["mentor_name"] for r in ai.match_startup(startups[0], mentors, top_n=4)]
    assert "Dr Bio" not in names


def test_startup_without_embedding_and_failed_embed_returns_empty(monkeypatch, mentors):
    monkeypatch.setattr(ai, "get_embedding", lambda text: [])
    assert ai.match_startup({"company_name": "X", "description": "d"}, mentors) == []


def test_grade_pair_returns_none_when_gemini_fails(startups, mentors):
    # The autouse fixture makes every client call raise
    assert ai.grade_pair(startups[0], mentors[0]) is None


def test_grade_pair_rejects_response_missing_grades(monkeypatch, startups, mentors):
    class Resp:
        text = '{"reasoning": "r", "domain_fit": 5, "insight": "i", "tags": []}'
    monkeypatch.setattr(ai, "generate_with_retry", lambda **kw: Resp())
    assert ai.grade_pair(startups[0], mentors[0]) is None


def test_generate_with_retry_retries_rate_limits(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: None)
    calls = []

    class Models:
        def generate_content(self, **kw):
            calls.append(kw)
            if len(calls) < 3:
                raise RuntimeError("429 RESOURCE_EXHAUSTED")
            return "ok"

    class Client:
        models = Models()

    monkeypatch.setattr(ai, "get_gen_client", lambda: Client())
    assert ai.generate_with_retry(model="m", contents="c") == "ok"
    assert len(calls) == 3


def test_generate_with_retry_does_not_retry_other_errors(monkeypatch):
    calls = []

    class Models:
        def generate_content(self, **kw):
            calls.append(1)
            raise ValueError("400 bad request")

    class Client:
        models = Models()

    monkeypatch.setattr(ai, "get_gen_client", lambda: Client())
    with pytest.raises(ValueError):
        ai.generate_with_retry(model="m", contents="c")
    assert len(calls) == 1


def test_get_client_creates_one_client_per_location_across_threads(monkeypatch):
    # Regression: racing threads each built a client; the extras were
    # garbage-collected, closing connections mid-request.
    monkeypatch.undo()  # restore the real get_client (autouse fixture replaced it)
    import google.genai

    created = []

    class FakeClient:
        def __init__(self, **kw):
            time.sleep(0.01)  # widen the race window
            created.append(kw["location"])

    monkeypatch.setattr(google.genai, "Client", FakeClient)
    monkeypatch.setattr(ai, "_clients", {})

    results = []
    threads = [threading.Thread(target=lambda: results.append(ai.get_client("loc-a"))) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert created == ["loc-a"]
    assert all(r is results[0] for r in results)
