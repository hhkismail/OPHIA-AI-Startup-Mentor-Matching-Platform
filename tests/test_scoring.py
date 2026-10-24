"""Synergy scoring maths: similarity percentile, rubric, blend."""

import numpy as np
import pytest

import ai_engine as ai


def test_cosine_similarity_basics():
    assert ai._cosine_similarity([1, 0], [1, 0]) == pytest.approx(1.0)
    assert ai._cosine_similarity([1, 0], [0, 1]) == pytest.approx(0.0)
    assert ai._cosine_similarity([1, 0], [2, 0]) == pytest.approx(1.0)  # scale-invariant


@pytest.mark.parametrize("a, b", [([], [1.0]), ([1.0], []), ([1.0, 0], [1.0]), ([0, 0], [1, 0])])
def test_cosine_similarity_degenerate_inputs_return_zero(a, b):
    # Missing, mismatched-dimension or zero vectors must not crash or match
    assert ai._cosine_similarity(a, b) == 0.0


def test_similarity_percentile_is_bounded_and_monotonic():
    values = [ai.similarity_percentile(s) for s in np.linspace(-1, 1, 41)]
    assert values == sorted(values)
    assert values[0] == 0.0 and values[-1] == 1.0


def test_similarity_percentile_matches_reference_points():
    ref = np.linspace(0.2, 0.7, 21)  # percentiles 0, 5, ..., 100
    assert ai.similarity_percentile(0.2, ref) == pytest.approx(0.0)
    assert ai.similarity_percentile(0.45, ref) == pytest.approx(0.5)
    assert ai.similarity_percentile(0.7, ref) == pytest.approx(1.0)


def test_default_reference_shows_raw_cosine_is_compressed():
    # The reason percentiles exist: the median pair is ~0.40, not ~0.0 or 0.5
    ref = ai.DEFAULT_SIM_REFERENCE
    assert len(ref) == 21 and all(np.diff(ref) > 0)
    assert 0.3 < ref[10] < 0.5


def test_build_similarity_reference(startups, mentors):
    ref = ai.build_similarity_reference(startups, mentors)
    sims = [ai._cosine_similarity(s["description_embedding"], m["bio_embedding"])
            for s in startups for m in mentors]
    assert len(ref) == 21
    assert ref[0] == pytest.approx(min(sims)) and ref[-1] == pytest.approx(max(sims))


@pytest.mark.parametrize("grades, expected", [
    ((1, 1, 1), 0.0), ((5, 5, 5), 1.0), ((3, 3, 3), 0.5), ((5, 3, 1), 0.5),
])
def test_rubric_score(grades, expected):
    g = dict(zip(("domain_fit", "need_fit", "market_fit"), grades))
    assert ai.rubric_score(g) == pytest.approx(expected)


def test_rubric_score_clamps_out_of_range_grades():
    assert ai.rubric_score({"domain_fit": 9, "need_fit": 0, "market_fit": 5}) == pytest.approx(
        ai.rubric_score({"domain_fit": 5, "need_fit": 1, "market_fit": 5}))


def test_rubric_score_rejects_missing_grade():
    with pytest.raises(KeyError):
        ai.rubric_score({"domain_fit": 5, "need_fit": 5})


def test_blend_synergy_weights():
    assert ai.blend_synergy(1.0, 0.0, sim_weight=0.4) == 40
    assert ai.blend_synergy(0.0, 1.0, sim_weight=0.4) == 60
    assert ai.blend_synergy(0.5, 0.5) == 50


def test_blend_synergy_without_rubric_uses_similarity_only():
    assert ai.blend_synergy(0.83, None) == 83


def test_embedding_text_recipes_include_context():
    s = {"description": "Slogan", "long_description": "Long text", "industry_tags": ["A", "B"]}
    assert ai.startup_embedding_text(s) == "Slogan\nLong text\nIndustries: A, B"

    m = {"title": "VP", "bio": "Bio", "skills": ["X", "Y"], "industry_tags": ["Y", "Z"]}
    assert ai.mentor_embedding_text(m) == "VP\nBio\nExpertise: X, Y, Z"  # deduplicated


def test_embedding_text_recipes_skip_missing_fields():
    assert ai.startup_embedding_text({"description": "Only this"}) == "Only this"
    assert ai.mentor_embedding_text({"bio": "Only bio"}) == "Only bio"
