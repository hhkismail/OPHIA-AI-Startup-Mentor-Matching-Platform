"""Capacity-aware assignment: correctness, constraints, and comparison with greedy baselines."""

import itertools
import random

import pytest

import assignment as asg


def test_capacity_from_hours_and_current_load():
    assert asg.mentor_capacity({"availability_hours": 8}, hours_per_mentorship=3) == 2
    assert asg.mentor_capacity({"availability_hours": 8}, active_mentorships=1, hours_per_mentorship=3) == 1
    assert asg.mentor_capacity({"availability_hours": 2}, active_mentorships=5, hours_per_mentorship=3) == 0
    assert asg.mentor_capacity({}, hours_per_mentorship=3) == 0


def test_the_classic_greedy_trap():
    # Both startups like mentor A most. Greedy gives A to s1 and leaves s2 with
    # a bad match; optimal gives A to s2, which has no good alternative.
    scores = {("s1", "A"): 90, ("s1", "B"): 85, ("s2", "A"): 88, ("s2", "B"): 20}
    cap = {"A": 1, "B": 1}
    assert asg.greedy_sequential(scores, cap) == {"s1": "A", "s2": "B"}       # total 110
    assert asg.assign_optimal(scores, cap) == {"s1": "B", "s2": "A"}          # total 173
    assert asg.greedy_independent(scores) == {"s1": "A", "s2": "A"}           # A overloaded


def test_respects_capacity():
    scores = {(f"s{i}", "A"): 99 for i in range(5)} | {(f"s{i}", "B"): 50 for i in range(5)}
    result = asg.assign_optimal(scores, {"A": 2, "B": 2})
    loads = [list(result.values()).count(m) for m in ("A", "B")]
    assert loads == [2, 2] and len(result) == 4  # 5th startup: no room anywhere


def test_never_uses_pairs_below_min_synergy():
    scores = {("s1", "A"): 40, ("s2", "A"): 80}
    assert asg.assign_optimal(scores, {"A": 2}, min_synergy=50) == {"s2": "A"}


def test_non_candidate_pairs_are_never_assigned():
    scores = {("s1", "A"): 70}
    assert asg.assign_optimal(scores, {"A": 0, "B": 5}) == {}


def test_empty_inputs():
    assert asg.assign_optimal({}, {"A": 3}) == {}
    assert asg.assign_optimal({("s1", "A"): 50}, {}) == {}


def brute_force_best(scores, cap, min_synergy=0):
    startups = sorted({s for s, _ in scores})
    mentors = sorted(cap)
    best = 0
    for choice in itertools.product([None, *mentors], repeat=len(startups)):
        if any(choice.count(m) > cap[m] for m in mentors):
            continue
        total, ok = 0, True
        for s, m in zip(startups, choice):
            if m is None:
                total += min_synergy
            elif (s, m) in scores and scores[(s, m)] >= min_synergy:
                total += scores[(s, m)]
            else:
                ok = False
                break
        if ok:
            best = max(best, total)
    return best


@pytest.mark.parametrize("seed", range(25))
def test_matches_brute_force_on_random_instances(seed):
    rng = random.Random(seed)
    startups = [f"s{i}" for i in range(rng.randint(1, 5))]
    mentors = [f"m{j}" for j in range(rng.randint(1, 4))]
    scores = {(s, m): rng.randint(0, 100) for s in startups for m in mentors if rng.random() < 0.8}
    cap = {m: rng.randint(0, 2) for m in mentors}
    min_syn = rng.choice([0, 30, 60])
    result = asg.assign_optimal(scores, cap, min_synergy=min_syn)

    for m in mentors:
        assert list(result.values()).count(m) <= cap[m]
    total = sum(scores[(s, m)] for s, m in result.items()) + min_syn * (len({s for s, _ in scores}) - len(result))
    assert total == brute_force_best(scores, cap, min_syn)


@pytest.mark.parametrize("seed", range(10))
def test_optimal_never_worse_than_sequential_greedy(seed):
    rng = random.Random(100 + seed)
    startups = [f"s{i}" for i in range(12)]
    mentors = [f"m{j}" for j in range(5)]
    scores = {(s, m): rng.randint(20, 100) for s in startups for m in rng.sample(mentors, 3)}
    cap = {m: rng.randint(1, 3) for m in mentors}
    opt = asg.summarize(asg.assign_optimal(scores, cap), scores, cap, len(startups))
    seq = asg.summarize(asg.greedy_sequential(scores, cap), scores, cap, len(startups))
    assert opt["total_synergy"] >= seq["total_synergy"]
    assert opt["mentors_over_capacity"] == 0


def test_summarize_counts_overload():
    scores = {("s1", "A"): 90, ("s2", "A"): 80}
    s = asg.summarize({"s1": "A", "s2": "A"}, scores, {"A": 1}, n_startups=3)
    assert s == {"assigned": 2, "unassigned": 1, "total_synergy": 170.0, "mean_synergy": 85.0,
                 "got_top_choice": 2, "mentors_over_capacity": 1, "excess_mentorships": 1, "max_load": 2}
