# evaluation_page.py
# Renders the evaluation results committed under ophia-nlp/output/ — how match
# quality was measured, with limitations. Works in every mode (no backend needed).

import json
from pathlib import Path

import streamlit as st

OUTPUT = Path(__file__).resolve().parent.parent / "ophia-nlp" / "output"


def _load(name: str):
    path = OUTPUT / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def render():
    st.subheader("Evaluation")
    st.write(
        "Each suggestion comes from embeddings (shortlist), Gemini grading three criteria "
        "against a rubric (domain, need, market fit), a blend of the two, a domain-fit gate, "
        "and a capacity-aware assignment. Each step was measured, below."
    )

    human, validation = _load("eval_human_results.json"), _load("eval_human_validation.json")
    if human:
        st.subheader("1. Agreement with human judgement")
        st.write(f"{human['n']} startup–mentor pairs, sampled evenly across the AI's score range, "
                 "labelled Good / OK / Bad **blind** (AI score hidden).")
        st.dataframe(hide_index=True, use_container_width=True, data=[{"Signal": name, "Rank correlation (Spearman)": m["spearman"],
                   "AUC good vs bad": m["auc_good_vs_bad"], "Weighted kappa": m["weighted_kappa"]}
                  for name, m in human["signals"].items()])
        st.caption("Gemini's rubric agrees with people far better than embedding similarity alone. "
                   "Kappa above 0.8 is conventionally 'almost perfect' agreement.")

    if validation:
        st.subheader("2. Fixing the main error, validated on held-out labels")
        st.write(
            "Most AI errors were mentors from the wrong industry scored as 'OK', because generic "
            "skills averaged up a poor domain fit. A **domain gate** (domain fit ≤ 2 → score capped "
            "at 49) was proposed, and the pass mark was committed *before* a second person labelled "
            f"{validation['n']} fresh pairs."
        )
        c1, c2, c3 = st.columns(3)
        c1.metric("Kappa without gate", validation["current"]["weighted_kappa"])
        c2.metric("Kappa with gate", validation["with_gate"]["weighted_kappa"],
                  round(validation["with_gate"]["weighted_kappa"] - validation["current"]["weighted_kappa"], 2))
        c3.metric("Gate-affected pairs judged bad", f"{validation['affected_labelled_bad']:.0%}")
        st.caption("Decision by the pre-registered rule: "
                   + ("**adopted**." if validation["adopt_gate"] else "**not adopted**."))

    scoring = _load("eval_results.json")
    if scoring:
        st.subheader("3. Does the score separate good from bad matches?")
        rows = scoring["scoring"]
        legacy = rows.get("legacy (Gemini 0-100)", {})
        current = next((v for k, v in rows.items() if "(current)" in k), {})
        st.write(f"{scoring['n_startups']} startups, comparing the mentor written for each startup "
                 "against random mentors.")
        c1, c2, c3 = st.columns(3)
        c1.metric("Random mentor, old 0-100 prompt", legacy.get("mean random"))
        c2.metric("Random mentor, rubric blend", current.get("mean random"))
        c3.metric("Right mentor picked", f"{current.get('final pick = intended', 0):.0%}",
                  f"{current.get('final pick = intended', 0) - rows['embedding rank only']['final pick = intended']:+.0%} vs embeddings alone")

    assignment = _load("eval_assignment.json")
    if assignment:
        st.subheader("4. Capacity-aware assignment")
        st.write("Mentors have limited hours. Picking each startup's favourite independently "
                 "overloads popular mentors; OPHIA assigns all startups jointly (Hungarian algorithm).")
        st.dataframe(hide_index=True, use_container_width=True, data=[{"Mentors available": size,
                   "Overloaded mentors (independent)": s["independent"]["mentors_over_capacity"],
                   "Mean synergy, first-come": s["sequential"]["mean_synergy"],
                   "Mean synergy, optimal": s["optimal"]["mean_synergy"],
                   "Startups placed, first-come → optimal": f"{s['sequential']['assigned']} → {s['optimal']['assigned']}"}
                  for size, s in assignment["summary"].items()])
        st.caption("With all 61 mentors there's no difference (the seeded data is ~1 mentor per startup); "
                   "it matters when mentors are scarce, as in a real programme.")

    st.subheader("Limitations")
    st.markdown(
        "- Mentors are AI-generated, not real people; startups come from the public YC dataset.\n"
        "- Human labels come from two team members (not independent of the project), 60 pairs in "
        "total, so differences below ~0.05 kappa are within noise.\n"
        "- 'Synergy' is OPHIA's own score; section 4 shows the solver optimises it, not that people "
        "would prefer every assignment."
    )
    if not any((human, validation, scoring, assignment)):
        st.info("No evaluation results found in ophia-nlp/output/.")
