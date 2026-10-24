"""
eval_assignment.py — when does capacity-aware assignment matter?

The seeded data has one generated mentor per startup, so conflicts over the
same mentor are rare. Real programmes usually have far fewer mentors than
startups. This experiment shrinks the mentor pool (random subsets, several
trials per size) and compares, on the same candidate scores:

  independent  — each startup takes its best mentor, capacity ignored (old OPHIA)
  sequential   — startups in random arrival order take their best mentor with room
  optimal      — assignment.assign_optimal (what OPHIA does now)

Candidates and scores are exactly what the backend uses: top 3 mentors by
similarity, graded by Gemini, blended synergy. Grades are cached in
output/eval_cache.json (shared with eval_scoring.py), so re-runs are free.

Run (from ophia-nlp/, needs Firestore seeded):  python eval_assignment.py
Results: output/eval_assignment.json
"""

import json
import random
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "ophia-data"))

import ai_engine as ai   # noqa: E402
import assignment as asg  # noqa: E402
import database          # noqa: E402

POOL_SIZES = [61, 30, 20, 15, 10]
TRIALS = 5
TOP_K = 3
SEED = 11
CACHE_PATH = HERE / "output" / "eval_cache.json"
RESULTS_PATH = HERE / "output" / "eval_assignment.json"
METRICS = ["assigned", "total_synergy", "mean_synergy", "got_top_choice",
           "mentors_over_capacity", "excess_mentorships", "max_load"]


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    startups = database.get_active_startups()
    mentors = database.get_available_mentors()
    names = [m["name"] for m in mentors]
    S = np.array([s["description_embedding"] for s in startups], dtype=float)
    M = np.array([m["bio_embedding"] for m in mentors], dtype=float)
    sim = (S / np.linalg.norm(S, axis=1, keepdims=True)) @ (M / np.linalg.norm(M, axis=1, keepdims=True)).T
    reference = ai.build_similarity_reference(startups, mentors)
    capacity_all = {m["name"]: asg.mentor_capacity(m) for m in mentors}

    rng = random.Random(SEED)
    scenarios = []  # (pool size, trial, mentor indices, arrival order)
    for size in POOL_SIZES:
        for trial in range(1 if size == len(mentors) else TRIALS):
            pool = sorted(rng.sample(range(len(mentors)), min(size, len(mentors))))
            order = [s["company_name"] for s in rng.sample(startups, len(startups))]
            scenarios.append((size, trial, pool, order))

    # Candidate pairs per scenario: top-K by similarity within the pool
    candidate_sets = []
    needed = set()
    for _, _, pool, _ in scenarios:
        pairs = []
        for i in range(len(startups)):
            top = sorted(pool, key=lambda j: -sim[i, j])[:TOP_K]
            pairs += [(i, j) for j in top]
        candidate_sets.append(pairs)
        needed.update(pairs)

    cache = json.loads(CACHE_PATH.read_text(encoding="utf-8")) if CACHE_PATH.exists() else {}
    key = lambda i, j: startups[i]["company_name"] + "|" + names[j]  # noqa: E731
    missing = [p for p in needed if not cache.get(key(*p), {}).get("rubric")]
    print(f"{len(scenarios)} scenarios, {len(needed)} distinct candidate pairs, {len(missing)} need grading")

    def grade(pair):
        return pair, ai.grade_pair(startups[pair[0]], mentors[pair[1]])

    with ThreadPoolExecutor(8) as pool:
        for n, ((i, j), g) in enumerate(pool.map(grade, missing), 1):
            if g:
                cache.setdefault(key(i, j), {})["rubric"] = g
            if n % 100 == 0:
                print(f"  graded {n}/{len(missing)}")
    CACHE_PATH.write_text(json.dumps(cache, indent=1), encoding="utf-8")

    def synergy(i, j):
        g = cache.get(key(i, j), {}).get("rubric")
        return ai.blend_synergy(ai.similarity_percentile(sim[i, j], reference), ai.rubric_score(g) if g else None)

    rows = []
    for (size, trial, pool, order), pairs in zip(scenarios, candidate_sets):
        scores = {(startups[i]["company_name"], names[j]): synergy(i, j) for i, j in pairs}
        cap = {names[j]: capacity_all[names[j]] for j in pool}
        n = len(startups)
        rows.append({
            "pool": size, "trial": trial, "capacity_slots": sum(cap.values()),
            "independent": asg.summarize(asg.greedy_independent(scores), scores, cap, n),
            "sequential": asg.summarize(asg.greedy_sequential(scores, cap, order=order), scores, cap, n),
            "optimal": asg.summarize(asg.assign_optimal(scores, cap), scores, cap, n),
        })

    # ── Report: mean over trials per pool size ────────────────────────────────
    summary = {}
    print(f"\n{len(startups)} startups, {asg.HOURS_PER_MENTORSHIP}h per mentorship. Mean over trials.\n")
    header = f"{'mentors':>8} {'slots':>6} {'method':<12}" + "".join(f"{m:>22}" for m in METRICS)
    print(header)
    for size in POOL_SIZES:
        trials = [r for r in rows if r["pool"] == size]
        summary[size] = {"capacity_slots": float(np.mean([r["capacity_slots"] for r in trials]))}
        for method in ("independent", "sequential", "optimal"):
            means = {m: round(float(np.mean([r[method][m] for r in trials])), 1) for m in METRICS}
            summary[size][method] = means
            print(f"{size:>8} {summary[size]['capacity_slots']:>6.0f} {method:<12}" +
                  "".join(f"{means[m]:>22}" for m in METRICS))
        gain = summary[size]["optimal"]["total_synergy"] - summary[size]["sequential"]["total_synergy"]
        print(f"{'':>8} {'':>6} optimal vs sequential: {gain:+.1f} total synergy, "
              f"{summary[size]['optimal']['assigned'] - summary[size]['sequential']['assigned']:+.1f} startups placed\n")

    RESULTS_PATH.write_text(json.dumps({
        "n_startups": len(startups), "n_mentors": len(mentors), "trials": TRIALS, "seed": SEED,
        "hours_per_mentorship": asg.HOURS_PER_MENTORSHIP, "top_k": TOP_K,
        "summary": summary, "runs": rows,
    }, indent=2), encoding="utf-8")
    print(f"Saved {RESULTS_PATH}")


if __name__ == "__main__":
    main()
