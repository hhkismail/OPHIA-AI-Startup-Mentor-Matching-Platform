"""Human-label evaluation: sampling, metrics, label storage, and the labelling UI."""

import json
from collections import Counter
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import eval_human as eh

APP = str(Path(__file__).resolve().parent.parent / "ophia-nlp" / "label_app.py")


def pair(s, m, synergy, rubric=None, sim=None):
    return {"startup_name": s, "mentor_name": m,
            "startup": {"description": f"{s} desc", "industry_tags": ["X"], "country": "US"},
            "mentor": {"title": "T", "bio": f"{m} bio", "skills": ["Y"]},
            "ai": {"synergy": synergy, "rubric": rubric if rubric is not None else synergy,
                   "similarity_pct": sim if sim is not None else synergy,
                   "grades": {"domain_fit": 3, "need_fit": 3, "market_fit": 3}, "reasoning": "because"}}


# ── Metrics ──────────────────────────────────────────────────────────────────

def test_kappa_perfect_and_chance():
    assert eh.weighted_kappa([0, 1, 2, 2], [0, 1, 2, 2]) == pytest.approx(1.0)
    # Constant predictions carry no information beyond chance
    assert eh.weighted_kappa([1, 1, 1, 1], [0, 1, 2, 1]) == pytest.approx(0.0)


def test_kappa_penalises_big_disagreements_more():
    small = eh.weighted_kappa([2, 1, 0, 0], [1, 1, 0, 0])   # one good-vs-ok
    big = eh.weighted_kappa([2, 1, 0, 0], [0, 1, 0, 2])     # good-vs-bad twice
    assert small > big


def test_ai_class_thresholds():
    assert [eh.ai_class(x) for x in (0, 49, 50, 79, 80, 100)] == [0, 0, 1, 1, 2, 2]


def test_agreement_on_a_perfect_ranker():
    scores, labels = [10, 20, 55, 65, 85, 95], [0, 0, 1, 1, 2, 2]
    m = eh.agreement(scores, labels)
    # Tied human labels cap Spearman below 1 even for a perfect ranker
    assert m["spearman"] == pytest.approx(0.956, abs=1e-3)
    assert m["auc_good_vs_bad"] == m["weighted_kappa"] == m["exact_agreement"] == 1.0


def test_agreement_on_an_inverted_ranker():
    m = eh.agreement([95, 85, 65, 55, 20, 10], [0, 0, 1, 1, 2, 2])
    assert m["spearman"] == pytest.approx(-0.956, abs=1e-3) and m["auc_good_vs_bad"] == 0.0


# ── Sampling ─────────────────────────────────────────────────────────────────

def test_sample_is_stratified_capped_and_deterministic():
    pairs = [pair(f"s{i % 30}", f"m{i}", synergy) for i, synergy in enumerate(list(range(0, 101)) * 3)]
    a = eh.stratified_sample(pairs, per_band=4)
    b = eh.stratified_sample(list(reversed(pairs)), per_band=4)
    assert [eh.pair_key(p) for p in a] == [eh.pair_key(p) for p in b]
    bands = Counter(next(i for i, (lo, hi) in enumerate(eh.BANDS) if lo <= p["ai"]["synergy"] <= hi) for p in a)
    assert sorted(bands.values()) == [4] * len(eh.BANDS)
    assert max(Counter(p["startup_name"] for p in a).values()) <= eh.MAX_PER_STARTUP


def test_sample_order_does_not_reveal_the_band():
    pairs = [pair(f"s{i}", "m", synergy) for i, synergy in enumerate(range(0, 101))]
    order = [p["ai"]["synergy"] for p in eh.stratified_sample(pairs, per_band=6, max_per_startup=1)]
    assert order != sorted(order) and order != sorted(order, reverse=True)


# ── Storage + report ─────────────────────────────────────────────────────────

def test_save_label_round_trip_and_validation(tmp_path):
    path = tmp_path / "labels.json"
    eh.save_label("a|b", "good", note=" fits ", labeller="me", path=path)
    eh.save_label("a|b", "ok", path=path)  # relabel overwrites
    assert eh.load_labels(path)["a|b"]["label"] == "ok"
    with pytest.raises(ValueError):
        eh.save_label("a|b", "great", path=path)


def test_report_compares_signals_and_finds_disagreements():
    sample = [pair("s1", "m", 95, rubric=95, sim=20), pair("s2", "m", 10, rubric=10, sim=90),
              pair("s3", "m", 60, rubric=60, sim=50), pair("s4", "m", 85, rubric=90, sim=30),
              pair("s5", "m", 20, rubric=15, sim=80), pair("s6", "m", 90, rubric=5, sim=99)]
    labels = {"s1|m": "good", "s2|m": "bad", "s3|m": "ok", "s4|m": "good", "s5|m": "bad", "s6|m": "bad"}
    data = eh.report_data(sample, {k: {"label": v, "note": ""} for k, v in labels.items()})
    assert data["n"] == 6
    sig = data["signals"]
    assert sig["Gemini rubric only"]["spearman"] > sig["embedding similarity only"]["spearman"]
    assert data["disagreements"][0]["pair"] == "s6|m"  # AI 90, human bad


def test_report_needs_a_few_labels():
    assert eh.report_data([pair("s1", "m", 50)], {}) == {"n": 0}


# ── UI ───────────────────────────────────────────────────────────────────────

@pytest.fixture
def labelling(tmp_path, monkeypatch):
    sample = [pair("BioCo", "Dr Bio", 91), pair("PayCo", "Ms Pay", 30)]
    sample_path, labels_path = tmp_path / "sample.json", tmp_path / "labels.json"
    sample_path.write_text(json.dumps(sample))
    monkeypatch.setenv("OPHIA_LABEL_SAMPLE", str(sample_path))
    monkeypatch.setenv("OPHIA_LABELS_PATH", str(labels_path))
    return labels_path


def text(at):
    return "\n".join(str(e.value) for e in [*at.markdown, *at.caption, *at.subheader, *at.success, *at.error])


def test_ui_hides_ai_scores(labelling):
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    shown = text(at)
    assert "BioCo" in shown and "Dr Bio" in shown
    assert "91" not in shown and "because" not in shown  # no AI score or reasoning


def test_ui_saves_labels_and_finishes(labelling):
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.text_input(key="note_BioCo|Dr Bio").input("strong fit").run()
    at.button(key="good_BioCo|Dr Bio").click().run()
    at.button(key="bad_PayCo|Ms Pay").click().run()
    saved = eh.load_labels(labelling)
    assert saved["BioCo|Dr Bio"]["label"] == "good" and saved["BioCo|Dr Bio"]["note"] == "strong fit"
    assert saved["PayCo|Ms Pay"]["label"] == "bad"
    assert "All 2 pairs labelled" in text(at)


def test_ui_undo(labelling):
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.button(key="good_BioCo|Dr Bio").click().run()
    at.button(key="undo").click().run()
    assert eh.load_labels(labelling) == {}
    assert "BioCo" in text(at)


def test_ui_without_sample(tmp_path, monkeypatch):
    monkeypatch.setenv("OPHIA_LABEL_SAMPLE", str(tmp_path / "missing.json"))
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert "eval_human.py build" in text(at)
