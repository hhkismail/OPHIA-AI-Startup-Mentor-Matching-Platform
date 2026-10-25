"""
eval_human.py — does the AI judge agree with a human?

eval_scoring.py checks the AI against mentors the AI itself wrote for each
startup, which is circular. This script checks it against human labels.

  python eval_human.py build    # once: pick a fixed, stratified sample of pairs
  streamlit run label_app.py    # label them blind (AI scores hidden)
  python eval_human.py report   # agreement metrics + biggest disagreements

  python eval_human.py build-validation      # fresh held-out batch for the domain gate
  streamlit run label_app.py -- validation   # label it
  python eval_human.py validate              # applies the pre-registered decision rule

The sample spans the whole AI score range (equal numbers per band), so the
result says whether the AI *ranks* pairs like a human, not just whether its
top picks look fine. Labels: good = would approve, ok = acceptable if nothing
better, bad = would reject.

The report also covers the feedback loop: approve/reject decisions made in
the dashboard (the `matches` collection) are compared with the AI scores.
"""

import json
import random
import sys
from collections import Counter
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr

HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "output"
SAMPLE_PATH = OUTPUT / "label_sample.json"
LABELS_PATH = OUTPUT / "human_labels.json"
CACHE_PATH = OUTPUT / "eval_cache.json"

BANDS = [(0, 39), (40, 59), (60, 79), (80, 89), (90, 100)]
PER_BAND = 8
MAX_PER_STARTUP = 2
SEED = 3
LABEL_VALUES = {"bad": 0, "ok": 1, "good": 2}


# ── Metrics ──────────────────────────────────────────────────────────────────

def ai_class(synergy: float, ok_at: float = 50, good_at: float = 80) -> int:
    """Maps a 0-100 score onto the 3 human labels (0 bad, 1 ok, 2 good)."""
    return 2 if synergy >= good_at else 1 if synergy >= ok_at else 0


def weighted_kappa(a: list[int], b: list[int], n_classes: int = 3) -> float:
    """Cohen's kappa with quadratic weights: agreement beyond chance, where
    'good vs bad' counts as a bigger disagreement than 'good vs ok'.
    1 = perfect, 0 = no better than chance."""
    observed = np.zeros((n_classes, n_classes))
    for x, y in zip(a, b):
        observed[x, y] += 1
    observed /= observed.sum()
    expected = np.outer(observed.sum(axis=1), observed.sum(axis=0))
    i, j = np.indices((n_classes, n_classes))
    weights = (i - j) ** 2 / (n_classes - 1) ** 2
    denom = (weights * expected).sum()
    return float(1 - (weights * observed).sum() / denom) if denom else 1.0


def auc(pos: list[float], neg: list[float]) -> float:
    if not pos or not neg:
        return float("nan")
    return sum((p > n) + 0.5 * (p == n) for p in pos for n in neg) / (len(pos) * len(neg))


def agreement(scores: list[float], labels: list[int]) -> dict:
    """How well a 0-100 score agrees with human labels (0/1/2)."""
    rho = spearmanr(scores, labels).statistic if len(set(labels)) > 1 else float("nan")
    return {
        "spearman": round(float(rho), 3),
        "auc_good_vs_bad": round(auc([s for s, y in zip(scores, labels) if y == 2],
                                     [s for s, y in zip(scores, labels) if y == 0]), 3),
        "weighted_kappa": round(weighted_kappa([ai_class(s) for s in scores], labels), 3),
        "exact_agreement": round(float(np.mean([ai_class(s) == y for s, y in zip(scores, labels)])), 3),
    }


# ── Sample ───────────────────────────────────────────────────────────────────

def stratified_sample(pairs: list[dict], per_band: int = PER_BAND, bands=BANDS,
                      max_per_startup: int = MAX_PER_STARTUP, seed: int = SEED) -> list[dict]:
    """Equal numbers of pairs per AI-score band, at most max_per_startup per startup."""
    rng = random.Random(seed)
    pairs = sorted(pairs, key=lambda p: (p["startup_name"], p["mentor_name"]))
    rng.shuffle(pairs)
    per_startup: Counter = Counter()
    chosen = []
    for lo, hi in bands:
        band = [p for p in pairs if lo <= p["ai"]["synergy"] <= hi]
        taken = 0
        for p in band:
            if taken == per_band:
                break
            if per_startup[p["startup_name"]] < max_per_startup:
                chosen.append(p)
                per_startup[p["startup_name"]] += 1
                taken += 1
    rng.shuffle(chosen)  # labelling order must not reveal the band
    return chosen


def graded_pairs() -> list[dict]:
    """Every pair in the eval cache that Gemini graded, with display text and AI scores."""
    sys.path.insert(0, str(HERE.parent / "ophia-data"))
    import ai_engine as ai
    import database

    startups = {s["company_name"]: s for s in database.get_active_startups()}
    mentors = {m["name"]: m for m in database.get_available_mentors()}
    reference = ai.build_similarity_reference(list(startups.values()), list(mentors.values()))
    cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))

    pairs = []
    for key, entry in cache.items():
        s_name, m_name = key.split("|", 1)
        g = entry.get("rubric")
        if not g or s_name not in startups or m_name not in mentors:
            continue
        s, m = startups[s_name], mentors[m_name]
        sim = ai._cosine_similarity(s["description_embedding"], m["bio_embedding"])
        pct = ai.similarity_percentile(sim, reference)
        pairs.append({
            "startup_name": s_name, "mentor_name": m_name,
            "startup": {k: s.get(k) for k in ("description", "long_description", "industry_tags", "country", "batch")},
            "mentor": {k: m.get(k) for k in ("title", "bio", "skills", "industry_tags", "availability_hours")},
            # Hidden from the labeller; used by the report
            "ai": {"synergy": ai.blend_synergy(pct, ai.rubric_score(g)),
                   "rubric": round(100 * ai.rubric_score(g)),
                   "similarity_pct": round(100 * pct),
                   "grades": {k: g[k] for k in ("domain_fit", "need_fit", "market_fit")},
                   "reasoning": g.get("reasoning", "")},
        })
    return pairs


def build():
    if SAMPLE_PATH.exists():
        raise SystemExit(f"{SAMPLE_PATH.name} already exists — labels refer to it. Delete it to rebuild.")
    pairs = graded_pairs()
    sample = stratified_sample(pairs)
    SAMPLE_PATH.write_text(json.dumps(sample, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"Sampled {len(sample)} of {len(pairs)} graded pairs → {SAMPLE_PATH}")
    print("Per band:", {f"{lo}-{hi}": sum(lo <= p["ai"]["synergy"] <= hi for p in sample) for lo, hi in BANDS})


# ── Held-out validation of the domain gate ───────────────────────────────────
#
# The first 40 labels showed the AI's errors were almost all "too generous" on
# mentors from the wrong industry: a low domain_fit averaged up by generic
# need/market grades. A candidate fix, DESIGNED AFTER SEEING THOSE LABELS:
#
#   domain gate — if domain_fit <= 2, synergy is capped at 49 (never "ok")
#
# It cuts errors 9 -> 5 on those 40, but that is in-sample. It is tested on a
# fresh batch, with the decision rule fixed (and committed) BEFORE labelling:
#
#   Adopt the gate only if, on the validation batch, BOTH
#     1. weighted kappa with the gate > weighted kappa without it, and
#     2. >= 70% of the pairs the gate changes are labelled "bad".

VALIDATION_PATH = OUTPUT / "label_sample_validation.json"
GATE_MAX_DOMAIN_FIT = 2
GATE_CAP = 49
ADOPT_MIN_BAD_SHARE = 0.70


def domain_gate(synergy: float, grades: dict) -> float:
    return min(synergy, GATE_CAP) if grades["domain_fit"] <= GATE_MAX_DOMAIN_FIT else synergy


def gate_changes(p: dict) -> bool:
    return domain_gate(p["ai"]["synergy"], p["ai"]["grades"]) != p["ai"]["synergy"]


def validation_sample(pairs: list[dict], exclude: set[str], n_affected: int = 10, n_other: int = 10,
                      seed: int = SEED + 1) -> list[dict]:
    """Fresh pairs: half that the gate would change, half stratified others, shuffled."""
    fresh = [p for p in pairs if pair_key(p) not in exclude]
    affected = [p for p in fresh if gate_changes(p)]
    others = [p for p in fresh if not gate_changes(p)]
    chosen = stratified_sample(affected, per_band=n_affected, bands=[(0, 100)], seed=seed)[:n_affected]
    per_band = -(-n_other // len(BANDS))  # ceil
    spread = stratified_sample(others, per_band=per_band, seed=seed)[:n_other]
    # Bands with too few pairs leave the batch short; top up from the rest
    taken = {pair_key(p) for p in spread}
    rest = [p for p in sorted(others, key=pair_key) if pair_key(p) not in taken]
    random.Random(seed).shuffle(rest)
    chosen += spread + rest[:n_other - len(spread)]
    random.Random(seed).shuffle(chosen)
    return chosen


def build_validation():
    if VALIDATION_PATH.exists():
        raise SystemExit(f"{VALIDATION_PATH.name} already exists — labels refer to it.")
    first = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    sample = validation_sample(graded_pairs(), exclude={pair_key(p) for p in first})
    VALIDATION_PATH.write_text(json.dumps(sample, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"Validation batch: {len(sample)} fresh pairs, {sum(map(gate_changes, sample))} changed by the gate")


def validate_data(sample: list[dict], labels: dict) -> dict:
    rows = [(p, LABEL_VALUES[labels[pair_key(p)]["label"]]) for p in sample if pair_key(p) in labels]
    y = [label for _, label in rows]
    current = [p["ai"]["synergy"] for p, _ in rows]
    gated = [domain_gate(p["ai"]["synergy"], p["ai"]["grades"]) for p, _ in rows]
    affected = [label for p, label in rows if gate_changes(p)]
    k_current = weighted_kappa([ai_class(s) for s in current], y)
    k_gated = weighted_kappa([ai_class(s) for s in gated], y)
    bad_share = sum(label == 0 for label in affected) / len(affected) if affected else float("nan")
    return {
        "n": len(rows), "gate_affected": len(affected),
        "current": agreement(current, y), "with_gate": agreement(gated, y),
        "affected_labelled_bad": round(bad_share, 3),
        "criterion_1_kappa_improves": bool(k_gated > k_current),
        "criterion_2_bad_share": bool(bad_share >= ADOPT_MIN_BAD_SHARE),
        "adopt_gate": bool(k_gated > k_current and bad_share >= ADOPT_MIN_BAD_SHARE),
    }


def validate():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sample = json.loads(VALIDATION_PATH.read_text(encoding="utf-8"))
    data = validate_data(sample, load_labels())
    if data["n"] < len(sample):
        raise SystemExit(f"Only {data['n']}/{len(sample)} validation pairs labelled")
    print(f"\nHELD-OUT VALIDATION ({data['n']} fresh pairs, {data['gate_affected']} changed by the gate)\n")
    for name in ("current", "with_gate"):
        print(f"  {name:<10}", data[name])
    print(f"\n  gate-affected pairs labelled bad: {data['affected_labelled_bad']:.0%}")
    print(f"  1. kappa improves:              {data['criterion_1_kappa_improves']}")
    print(f"  2. >= {ADOPT_MIN_BAD_SHARE:.0%} of affected are bad:  {data['criterion_2_bad_share']}")
    print(f"\n  DECISION (pre-registered rule): {'ADOPT the gate' if data['adopt_gate'] else 'do NOT adopt the gate'}")
    (OUTPUT / "eval_human_validation.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


# ── Labels ───────────────────────────────────────────────────────────────────

def pair_key(p: dict) -> str:
    return f"{p['startup_name']}|{p['mentor_name']}"


def load_labels(path: Path = LABELS_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_label(key: str, label: str, note: str = "", labeller: str = "", path: Path = LABELS_PATH):
    import datetime
    if label not in LABEL_VALUES:
        raise ValueError(f"label must be one of {list(LABEL_VALUES)}")
    labels = load_labels(path)
    labels[key] = {"label": label, "note": note.strip(), "labeller": labeller,
                   "at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(labels, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)  # atomic: a crash mid-write never corrupts earlier labels


# ── Report ───────────────────────────────────────────────────────────────────

def report_data(sample: list[dict], labels: dict) -> dict:
    rows = [(p, LABEL_VALUES[labels[pair_key(p)]["label"]]) for p in sample if pair_key(p) in labels]
    if len(rows) < 5:
        return {"n": len(rows)}
    y = [label for _, label in rows]
    signals = {
        "blended synergy (what OPHIA uses)": [p["ai"]["synergy"] for p, _ in rows],
        "Gemini rubric only": [p["ai"]["rubric"] for p, _ in rows],
        "embedding similarity only": [p["ai"]["similarity_pct"] for p, _ in rows],
    }
    disagreements = sorted(rows, key=lambda r: -abs(r[0]["ai"]["synergy"] / 50 - r[1]))[:5]
    confusion = Counter((ai_class(p["ai"]["synergy"]), label) for p, label in rows)
    return {
        "n": len(rows),
        "label_counts": dict(Counter(labels[pair_key(p)]["label"] for p, _ in rows)),
        "signals": {name: agreement(scores, y) for name, scores in signals.items()},
        "confusion": {f"ai={a} human={h}": n for (a, h), n in sorted(confusion.items())},
        "disagreements": [{
            "pair": pair_key(p), "human": labels[pair_key(p)]["label"],
            "human_note": labels[pair_key(p)]["note"], "ai_synergy": p["ai"]["synergy"],
            "ai_grades": p["ai"]["grades"], "ai_reasoning": p["ai"]["reasoning"],
        } for p, _ in disagreements],
    }


def decisions_data() -> dict:
    """Feedback loop: do the admin's approve/reject decisions match the AI scores?"""
    sys.path.insert(0, str(HERE.parent / "ophia-data"))
    import database
    try:
        docs = [d.to_dict() for d in database.get_db().collection("matches").stream()]
    except Exception as e:
        return {"error": str(e)}
    approved = [m["synergy"] for m in docs if m.get("status") == "approved"]
    rejected = [m["synergy"] for m in docs if m.get("status") == "rejected"]
    return {"approved": len(approved), "rejected": len(rejected),
            "mean_synergy_approved": round(float(np.mean(approved)), 1) if approved else None,
            "mean_synergy_rejected": round(float(np.mean(rejected)), 1) if rejected else None,
            "auc_approved_vs_rejected": round(auc(approved, rejected), 3)}


def report():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sample = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    data = report_data(sample, load_labels())
    if data["n"] < 5:
        raise SystemExit(f"Only {data['n']} pairs labelled — label at least 5 (streamlit run label_app.py)")

    print(f"\n{data['n']} labelled pairs: {data['label_counts']}\n")
    print("AGREEMENT WITH HUMAN LABELS")
    print("  spearman: rank correlation (1 = same order) · AUC: P(a 'good' pair outscores a 'bad' one)")
    print("  kappa: chance-corrected agreement after mapping scores to bad <50 ≤ ok <80 ≤ good\n")
    print(f"  {'signal':<36}{'spearman':>10}{'AUC':>8}{'kappa':>8}{'exact':>8}")
    for name, m in data["signals"].items():
        print(f"  {name:<36}{m['spearman']:>10}{m['auc_good_vs_bad']:>8}{m['weighted_kappa']:>8}{m['exact_agreement']:>8}")
    print("\nCONFUSION (0 bad, 1 ok, 2 good):", data["confusion"])
    print("\nBIGGEST DISAGREEMENTS")
    for d in data["disagreements"]:
        print(f"\n  {d['pair']}: human={d['human']}  AI={d['ai_synergy']} {d['ai_grades']}")
        if d["human_note"]:
            print(f"    your note: {d['human_note']}")
        print(f"    AI reasoning: {d['ai_reasoning'][:300]}")

    data["decisions"] = decisions_data()
    print("\nFEEDBACK LOOP — dashboard decisions vs AI score:", data["decisions"])
    (OUTPUT / "eval_human_results.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved {OUTPUT / 'eval_human_results.json'}")


if __name__ == "__main__":
    {"build": build, "report": report, "build-validation": build_validation,
     "validate": validate}.get(sys.argv[1] if len(sys.argv) > 1 else "", lambda: print(__doc__))()
