"""
eval_scoring.py — measures how well OPHIA finds and scores mentor matches.

Ground truth: embed_data.py writes each mentor FOR one startup
(`generated_for`). That pairing is used as the "correct" mentor. It does not
come from the embeddings, so the similarity score can't pass by definition.
Caveat: these mentors were written to fit their startup, so they're easy
positives — a sanity check, not a substitute for human-labelled pairs.

Measures:
  1. Retrieval   — rank of the intended mentor among all mentors (recall@k, MRR),
                   for the old slogan-only embedding text vs the current recipe
  2. Separation  — AUC of synergy: intended mentor vs random mentors
  3. Spread      — how different the synergy scores of each startup's top 3 are
for the legacy scorer (Gemini picks 0-100) vs the current rubric + similarity
blend, plus a sweep over SIM_WEIGHT.

Run (from ophia-nlp/, needs Firestore seeded):  python eval_scoring.py
Results are written to output/eval_results.json. Gemini replies are cached in
output/eval_cache.json, so re-runs are free; delete it to re-grade.
"""

import json
import random
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "ophia-data"))

import ai_engine as ai  # noqa: E402
import database         # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SEED = 7
NEGATIVES_PER_STARTUP = 2
TOP_K = 3
CACHE_PATH = HERE / "output" / "eval_cache.json"
RESULTS_PATH = HERE / "output" / "eval_results.json"

# ── Legacy scorer (what OPHIA used before), kept here only for comparison ────
LEGACY_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "synergy": {"type": "INTEGER", "description": "Match synergy score from 0 to 100"},
        "insight": {"type": "STRING"},
        "tags": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["synergy", "insight", "tags"],
}
LEGACY_PROMPT = """
You are OPHIA, an AI ecosystem orchestrator for an innovation platform.

Evaluate this mentor-startup match and return a structured assessment.

STARTUP:
- Name: {startup_name}
- Description: {startup_description}
- Industry Tags: {startup_tags}

MENTOR:
- Name: {mentor_name}
- Title: {mentor_title}
- Bio: {mentor_bio}
- Skills: {mentor_skills}

Instructions:
- synergy: Score from 0-100 reflecting how well this mentor's expertise fits the startup's needs.
  (90-100 = exceptional alignment, 70-89 = strong, 50-69 = moderate, below 50 = weak)
- insight: Write EXACTLY 2 sentences. First sentence explains the core expertise alignment.
  Second sentence explains what specific outcome this mentor can drive for the startup.
- tags: 2-4 short taxonomy tags that describe the overlap (e.g. "AI/ML", "B2B Sales", "Series A Ready").
"""


def legacy_grade(startup: dict, mentor: dict):
    from google.genai import types
    prompt = LEGACY_PROMPT.format(
        startup_name=startup["company_name"], startup_description=startup["description"],
        startup_tags=", ".join(startup.get("industry_tags", [])), mentor_name=mentor["name"],
        mentor_title=mentor.get("title", ""), mentor_bio=mentor.get("bio", ""),
        mentor_skills=", ".join(mentor.get("skills", [])),
    )
    try:
        r = ai.generate_with_retry(
            model=ai.GEN_MODEL, contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json", response_schema=LEGACY_SCHEMA, temperature=0.3),
        )
        return int(json.loads(r.text)["synergy"])
    except Exception as e:
        print(f"  legacy grading failed: {e}")
        return None


# ── Helpers ──────────────────────────────────────────────────────────────────

def auc(pos: list[float], neg: list[float]) -> float:
    """P(random positive scores higher than random negative); ties count half."""
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def normalize(m: np.ndarray) -> np.ndarray:
    return m / np.linalg.norm(m, axis=1, keepdims=True)


def retrieval_metrics(sim: np.ndarray, truth: list[int]) -> dict:
    """sim: startups x mentors; truth[i] = index of startup i's intended mentor."""
    ranks = [int((sim[i] > sim[i, t]).sum()) + 1 for i, t in enumerate(truth)]
    return {
        "recall@1": float(np.mean([r <= 1 for r in ranks])),
        "recall@3": float(np.mean([r <= 3 for r in ranks])),
        "recall@5": float(np.mean([r <= 5 for r in ranks])),
        "MRR": float(np.mean([1 / r for r in ranks])),
        "median_rank": float(np.median(ranks)),
    }


def embed_all(texts: list[str]) -> np.ndarray:
    with ThreadPoolExecutor(8) as ex:
        return np.array(list(ex.map(ai.get_embedding, texts)), dtype=float)


def main():
    startups = database.get_active_startups()
    mentors = database.get_available_mentors()
    generated = json.loads((HERE / "output" / "mentors_embedded.json").read_text(encoding="utf-8"))
    generated_for = {m["name"]: m["generated_for"] for m in generated if m.get("generated_for")}

    m_index = {m["name"]: j for j, m in enumerate(mentors)}
    owner = {s: name for name, s in generated_for.items()}
    eval_startups = [s for s in startups if owner.get(s["company_name"]) in m_index]
    truth = [m_index[owner[s["company_name"]]] for s in eval_startups]
    print(f"Evaluating {len(eval_startups)} startups against {len(mentors)} mentors\n")

    # ── 1. Retrieval: old text recipe vs current ─────────────────────────────
    current_sim = normalize(np.array([s["description_embedding"] for s in eval_startups])) @ \
        normalize(np.array([m["bio_embedding"] for m in mentors])).T
    print("Embedding the old slogan-only texts for comparison...")
    old_sim = normalize(embed_all([s["description"] for s in eval_startups])) @ \
        normalize(embed_all([m["bio"] for m in mentors])).T
    retrieval = {"old (slogan / bio only)": retrieval_metrics(old_sim, truth),
                 "current (full text recipe)": retrieval_metrics(current_sim, truth)}

    # ── Pairs to grade ───────────────────────────────────────────────────────
    rng = random.Random(SEED)
    pairs = set()          # (startup idx, mentor idx)
    positives, negatives, top3 = [], [], {}
    for i, t in enumerate(truth):
        positives.append((i, t)); pairs.add((i, t))
        others = [j for j in range(len(mentors)) if j != t]
        for j in rng.sample(others, NEGATIVES_PER_STARTUP):
            negatives.append((i, j)); pairs.add((i, j))
        top3[i] = [int(j) for j in np.argsort(-current_sim[i])[:TOP_K]]
        pairs.update((i, j) for j in top3[i])

    cache = json.loads(CACHE_PATH.read_text(encoding="utf-8")) if CACHE_PATH.exists() else {}

    def cache_key(i, j):
        return eval_startups[i]["company_name"] + "|" + mentors[j]["name"]

    def grade(pair):
        # Only successful grades are cached, so a re-run retries failures
        entry = dict(cache.get(cache_key(*pair), {}))
        if entry.get("legacy") is None:
            entry["legacy"] = legacy_grade(eval_startups[pair[0]], mentors[pair[1]])
        if entry.get("rubric") is None:
            entry["rubric"] = ai.grade_pair(eval_startups[pair[0]], mentors[pair[1]])
        return pair, entry

    print(f"Grading {len(pairs)} pairs with both scorers...")
    with ThreadPoolExecutor(4) as ex:
        graded = dict(ex.map(grade, sorted(pairs)))
    for (i, j), entry in graded.items():
        cache[cache_key(i, j)] = {k: v for k, v in entry.items() if v is not None}
    CACHE_PATH.write_text(json.dumps(cache, indent=1), encoding="utf-8")

    # ── 2 + 3. Separation and spread per scorer ──────────────────────────────
    ref = ai.build_similarity_reference(startups, mentors)

    def scorer_legacy(i, j):
        return graded[(i, j)]["legacy"]

    def make_blend(w):
        def f(i, j):
            g = graded[(i, j)]["rubric"]
            sim_pct = ai.similarity_percentile(current_sim[i, j], ref)
            return ai.blend_synergy(sim_pct, ai.rubric_score(g) if g else None, sim_weight=w)
        return f

    # Compare every scorer on exactly the same pairs: those both scorers graded
    ok = {p for p, e in graded.items() if e["legacy"] is not None and e["rubric"] is not None}
    failed = len(graded) - len(ok)
    positives = [p for p in positives if p in ok]
    negatives = [p for p in negatives if p in ok]
    top3 = {i: js for i, js in top3.items() if all((i, j) in ok for j in js)}

    def evaluate(fn):
        pos = [fn(i, j) for i, j in positives]
        neg = [fn(i, j) for i, j in negatives]
        top = [[fn(i, j) for j in js] for i, js in top3.items()]
        # What the app actually does: grade the top 3, show the highest score
        picks = [js[int(np.argmax(t))] for js, t in zip(top3.values(), top)]
        hits = [pick == truth[i] for i, pick in zip(top3, picks)]
        return {
            "final pick = intended": round(float(np.mean(hits)), 2),
            "AUC intended vs random": round(auc(pos, neg), 3),
            "mean intended": round(float(np.mean(pos)), 1),
            "mean random": round(float(np.mean(neg)), 1),
            "top-3 mean range": round(float(np.mean([max(t) - min(t) for t in top])), 1),
            "top-3 distinct scores": len({s for t in top for s in t}),
        }

    scorers = {"embedding rank only": {
        "final pick = intended": round(float(np.mean([top3[i][0] == truth[i] for i in top3])), 2)}}
    scorers["legacy (Gemini 0-100)"] = evaluate(scorer_legacy)
    for w in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0):
        label = f"blend w={w}" + (" (current)" if w == ai.SIM_WEIGHT else "")
        scorers[label] = evaluate(make_blend(w))

    # ── Report ───────────────────────────────────────────────────────────────
    print("\n1. RETRIEVAL — where does the intended mentor rank among", len(mentors), "?")
    for name, r in retrieval.items():
        print(f"   {name:<28} " + "  ".join(f"{k}={v:.2f}" for k, v in r.items()))

    print("\n2/3. SCORING  (w = weight on similarity percentile; w=0 is rubric only, w=1 similarity only)")
    print(f"   {len(positives)} intended + {len(negatives)} random pairs, {len(top3)} top-3 sets; "
          f"{failed} pairs excluded because a grade failed")
    cols = ["final pick = intended", "AUC intended vs random", "mean intended", "mean random",
            "top-3 mean range", "top-3 distinct scores"]
    print(f"   {'scorer':<24}" + "".join(f"{c:>24}" for c in cols))
    for name, r in scorers.items():
        print(f"   {name:<24}" + "".join(f"{r.get(c, '-'):>24}" for c in cols))

    RESULTS_PATH.write_text(json.dumps({
        "n_startups": len(eval_startups), "n_mentors": len(mentors), "seed": SEED,
        "pairs_excluded_failed_grade": failed,
        "retrieval": retrieval, "scoring": scorers,
    }, indent=2), encoding="utf-8")
    print(f"\nSaved {RESULTS_PATH}")


if __name__ == "__main__":
    main()
