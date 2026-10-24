"""
assignment.py — capacity-aware startup-to-mentor assignment.

Picking each startup's best mentor independently can hand one popular mentor
ten startups. Here every mentor has a capacity (monthly hours divided by
hours per mentorship, minus mentorships they already run), and all startups
are assigned at once to maximise total synergy.

Method: give each mentor one "slot" column per unit of capacity and add one
"leave unassigned" column per startup, worth `min_synergy`. Assigning startups
to columns is then a rectangular assignment problem, solved exactly by the
Hungarian algorithm (scipy.optimize.linear_sum_assignment). The unassigned
columns mean a startup is left without a mentor rather than forced into a
pairing scoring below `min_synergy`.

Two baselines, used by eval_assignment.py:
  greedy_independent — each startup takes its best mentor, capacity ignored
                       (what OPHIA did before)
  greedy_sequential  — startups in order, each takes its best mentor that
                       still has room (a reasonable manual process)
"""

import os

import numpy as np
from scipy.optimize import linear_sum_assignment

# How many hours per month one mentorship takes; capacity = hours // this
HOURS_PER_MENTORSHIP = int(os.getenv("HOURS_PER_MENTORSHIP", "3"))

_FORBIDDEN = -1e9


def mentor_capacity(mentor: dict, active_mentorships: int = 0,
                    hours_per_mentorship: int = HOURS_PER_MENTORSHIP) -> int:
    """Free slots: monthly hours // hours per mentorship, minus current load."""
    return max(0, int(mentor.get("availability_hours", 0)) // hours_per_mentorship - active_mentorships)


def assign_optimal(scores: dict[tuple[str, str], float], capacity: dict[str, int],
                   min_synergy: float = 0) -> dict[str, str]:
    """
    scores:   {(startup, mentor): synergy} for the candidate pairs (others are not allowed)
    capacity: {mentor: free slots}
    Returns {startup: mentor} maximising total synergy, every mentor within capacity.
    Pairs scoring below min_synergy are never used.
    """
    startups = sorted({s for s, _ in scores})
    slots = [m for m in sorted(capacity) for _ in range(max(0, capacity[m]))]
    if not startups:
        return {}

    n_s, n_slots = len(startups), len(slots)
    utility = np.full((n_s, n_slots + n_s), _FORBIDDEN)
    for i, s in enumerate(startups):
        for k, m in enumerate(slots):
            score = scores.get((s, m))
            if score is not None and score >= min_synergy:
                utility[i, k] = score
        utility[i, n_slots + i] = min_synergy  # this startup's "unassigned" option

    rows, cols = linear_sum_assignment(utility, maximize=True)
    return {startups[r]: slots[c] for r, c in zip(rows, cols) if c < n_slots}


def greedy_independent(scores: dict[tuple[str, str], float]) -> dict[str, str]:
    """Each startup's best-scoring mentor, ignoring capacity."""
    best: dict[str, tuple[float, str]] = {}
    for (s, m), score in scores.items():
        if s not in best or score > best[s][0] or (score == best[s][0] and m < best[s][1]):
            best[s] = (score, m)
    return {s: m for s, (_, m) in best.items()}


def greedy_sequential(scores: dict[tuple[str, str], float], capacity: dict[str, int],
                      order: list[str] | None = None, min_synergy: float = 0) -> dict[str, str]:
    """Startups in `order` (default: alphabetical), each takes its best mentor with room left."""
    left = dict(capacity)
    by_startup: dict[str, list[tuple[float, str]]] = {}
    for (s, m), score in scores.items():
        by_startup.setdefault(s, []).append((score, m))
    result = {}
    for s in order or sorted(by_startup):
        for score, m in sorted(by_startup.get(s, []), key=lambda x: (-x[0], x[1])):
            if score >= min_synergy and left.get(m, 0) > 0:
                result[s] = m
                left[m] -= 1
                break
    return result


def summarize(assignment: dict[str, str], scores: dict[tuple[str, str], float],
              capacity: dict[str, int], n_startups: int) -> dict:
    """Quality and feasibility numbers for comparing assignments."""
    load: dict[str, int] = {}
    for m in assignment.values():
        load[m] = load.get(m, 0) + 1
    over = {m: n - capacity.get(m, 0) for m, n in load.items() if n > capacity.get(m, 0)}
    chosen = [scores[(s, m)] for s, m in assignment.items()]
    top_choice = greedy_independent(scores)
    return {
        "assigned": len(assignment),
        "unassigned": n_startups - len(assignment),
        "total_synergy": round(float(sum(chosen)), 1),
        "mean_synergy": round(float(np.mean(chosen)), 1) if chosen else 0.0,
        "got_top_choice": sum(top_choice.get(s) == m for s, m in assignment.items()),
        "mentors_over_capacity": len(over),
        "excess_mentorships": sum(over.values()),
        "max_load": max(load.values(), default=0),
    }
