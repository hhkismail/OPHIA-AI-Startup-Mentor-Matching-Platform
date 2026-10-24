"""Data pipeline guards: unique mentor generation and seeding."""

import json

import pytest

import embed_data
import seed_db


class FakeModels:
    def __init__(self, replies):
        self.replies = list(replies)

    def generate_content(self, **kw):
        reply = self.replies.pop(0)

        class R:
            text = json.dumps(reply)
        return R()


class FakeClient:
    def __init__(self, replies):
        self.models = FakeModels(replies)


STARTUP = {"company_name": "BioCo", "description": "d", "industry_tags": ["Bio"], "country": "US"}


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(embed_data.time, "sleep", lambda s: None)


def test_generate_mentor_retries_on_duplicate_name(monkeypatch):
    # Regression: Gemini reused names, leaving 18 unique mentors out of 50
    fake = FakeClient([{"name": "Ann", "bio": "b"}, {"name": "Bo", "bio": "b"}])
    monkeypatch.setattr(embed_data, "gen_client", lambda: fake)
    assert embed_data.generate_mentor(STARTUP, used_names={"Ann"})["name"] == "Bo"


def test_generate_mentor_gives_up_instead_of_using_a_placeholder(monkeypatch):
    # Regression: failures used to save a fixed "Alex Morgan" placeholder
    fake = FakeClient([{"name": "Ann", "bio": "b"}] * embed_data.MAX_RETRIES)
    monkeypatch.setattr(embed_data, "gen_client", lambda: fake)
    assert embed_data.generate_mentor(STARTUP, used_names={"Ann"}) is None


def test_generate_mentor_rejects_incomplete_profiles(monkeypatch):
    fake = FakeClient([{"name": "Ann"}, {"name": "Ann", "bio": "ok"}])
    monkeypatch.setattr(embed_data, "gen_client", lambda: fake)
    assert embed_data.generate_mentor(STARTUP, used_names=set())["bio"] == "ok"


def test_used_names_are_in_the_prompt(monkeypatch):
    seen = []

    class Models:
        def generate_content(self, **kw):
            seen.append(kw["contents"])
            raise RuntimeError("stop")

    monkeypatch.setattr(embed_data, "gen_client", lambda: type("C", (), {"models": Models()})())
    embed_data.generate_mentor(STARTUP, used_names={"Zed Q", "Amy P"})
    assert "Amy P, Zed Q" in seen[0]


def test_slug():
    assert seed_db._slug("Dr. L. Wong") == "dr__l__wong"
    assert seed_db._slug("a" * 80) == "a" * 50


def test_load_mentors_dedupes_and_skips_failed_embeddings(monkeypatch, tmp_path):
    curated = [{"name": "Ann", "bio": "b1"}, {"name": "Bo", "bio": "FAIL"}]
    generated = [{"name": "Ann", "bio": "dup"}, {"name": "Cy", "bio": "b3"}]
    (tmp_path / "c.json").write_text(json.dumps(curated))
    (tmp_path / "g.json").write_text(json.dumps(generated))
    monkeypatch.setattr(seed_db, "CURATED_MENTORS", tmp_path / "c.json")
    monkeypatch.setattr(seed_db, "PIPELINE_MENTORS", tmp_path / "g.json")
    monkeypatch.setattr(seed_db, "get_embedding", lambda text: [] if "FAIL" in text else [1.0])

    mentors = seed_db.load_mentors()

    assert [m["name"] for m in mentors] == ["Ann", "Cy"]
    assert mentors[0]["bio"] == "b1"  # curated wins over generated duplicate


def test_load_startups_falls_back_to_samples(monkeypatch, tmp_path):
    monkeypatch.setattr(seed_db, "PIPELINE_STARTUPS", tmp_path / "missing.json")
    monkeypatch.setattr(seed_db, "get_embedding", lambda text: [1.0])
    assert [s["company_name"] for s in seed_db.load_startups()] == ["DataShield", "GreenLedger", "MediCore AI"]


def test_committed_mentor_data_has_unique_names_and_vectors():
    # Regression: all 50 generated mentors were one placeholder with one vector
    path = embed_data.OUT_MENTORS
    mentors = json.loads(path.read_text(encoding="utf-8"))
    assert len({m["name"] for m in mentors}) == len(mentors)
    assert len({tuple(m["bio_embedding"][:8]) for m in mentors}) == len(mentors)
    assert all(m.get("generated_for") for m in mentors)
