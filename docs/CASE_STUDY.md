# OPHIA: case study

How a 48-hour hackathon prototype became a measured, tested system: what was wrong with it,
what I changed, and the evidence for each change. For a quick overview, see the
[README](../README.md).

- [Starting point](#starting-point)
- [1. Measure the scorer before tuning it](#1-measure-the-scorer-before-tuning-it)
- [2. Don't grade the AI with its own answers](#2-dont-grade-the-ai-with-its-own-answers)
- [3. Pre-register the fix](#3-pre-register-the-fix)
- [4. Assign mentors jointly, within capacity](#4-assign-mentors-jointly-within-capacity)
- [5. Make the state the source of truth](#5-make-the-state-the-source-of-truth)
- [6. Fail closed, and keep the bill at zero](#6-fail-closed-and-keep-the-bill-at-zero)
- [7. Tests that can fail](#7-tests-that-can-fail)
- [Full evaluation results](#full-evaluation-results)
- [Limitations](#limitations)

---

## Starting point

At the end of the hackathon the embedding pipeline and AI engine existed, but:

- The backend wasn't connected to them: `/api/linkages` returned two hardcoded suggestions,
  and approval printed a line without storing anything.
- The engine asked Gemini for a single 0–100 "synergy" score per pair, with no way to tell
  whether it meant anything.
- Every generated mentor had fallen back to the same placeholder, "Alex Morgan", so the
  mentor data was unusable.
- There was no lifecycle: `state_machine.py` was a one-line placeholder, and nothing
  stopped a match being approved twice.
- There were no tests.

The data pipeline was rebuilt (retries, no placeholder fallback, 49
unique mentors), the backend was wired to the engine and Firestore, and then each design
question below was answered with a measurement.

## 1. Measure the scorer before tuning it

**Problem.** Is the 0–100 score any good? Each generated mentor records which startup it was
written for, so there is a known "intended" mentor per startup to test against.

**Finding.** The old prompt gave *random* mentors **61/100** on average. A score that rates a
random mentor as a decent match can't separate good from bad.

**Change.** Gemini now grades three criteria on 1–5 (domain fit, need fit, market fit), each
with written anchors for every score, reasoning first, temperature 0. The rubric is
blended with embedding similarity converted to a percentile (raw cosine similarity bunches
between 0.3 and 0.7, so a raw value means little):

```
synergy = 0.4 × similarity percentile + 0.6 × rubric score
```

**Result.** Random mentors: **61 → 36**. The intended mentor is picked **86%** of the time
(embeddings alone 73%, old prompt 76%, ceiling 90% because some generated mentors genuinely
suit several startups).

## 2. Don't grade the AI with its own answers

**Problem.** Section 1 measures the AI against mentors the AI generated: circular.

**Change.** A blind labelling app (`ophia-nlp/label_app.py`): 40 pairs sampled evenly across
the AI's score range, labelled Good / OK / Bad with the AI score hidden.

**Result.**

| Signal | Spearman | AUC good vs bad | Weighted kappa |
|---|---|---|---|
| Blended synergy (what OPHIA uses) | 0.908 | 1.0 | 0.849 |
| Gemini rubric only | 0.906 | 1.0 | 0.904 |
| Embedding similarity only | 0.776 | 0.963 | 0.522 |

The rubric does most of the work; on the hard middle cases similarity alone is close to
useless (kappa 0.24 vs 0.80). The 0.4 similarity weight is within noise of the best
weight, so it was kept rather than overfitted to 40 labels.

## 3. Pre-register the fix

**Problem.** Reading the disagreements showed one main error pattern: mentors from the
**wrong industry** scored "OK", because strong generic skills averaged up a poor domain fit.

**Change.** A domain gate: if domain fit ≤ 2, the score is capped at 49 (below "possible
match").

**How it was tested.** Tuning a rule on the same 40 labels that revealed the problem would
overfit. So the rule and its pass mark were committed *before* new data existed
([`91afa6c`](https://github.com/hhkismail/OPHIA-AI-Startup-Mentor-Matching-Platform/commit/91afa6c)),
and a second person labelled 20 fresh pairs.

**Result.** Kappa **0.64 → 0.96** on the held-out pairs; **9 of 10** gate-affected pairs were
judged bad by the labeller. Adopted in
[`fe98ee3`](https://github.com/hhkismail/OPHIA-AI-Startup-Mentor-Matching-Platform/commit/fe98ee3).

## 4. Assign mentors jointly, within capacity

**Problem.** If each startup takes its own best mentor, popular mentors get far more
startups than their monthly hours allow.

**Change.** `ophia-nlp/assignment.py` solves all startups at once with the Hungarian
algorithm (`scipy.optimize.linear_sum_assignment`). Each mentor contributes one column per
free slot (monthly hours ÷ 3 hours per mentorship, minus active workspaces and pending
suggestions). Each startup also gets an "unassigned" column worth the minimum acceptable
score, so a startup whose only options are weak is left for a human instead of given a bad
mentor.

**Result.** With the full pool of 61 mentors there is no difference (the seeded data is
about one mentor per startup). With mentors scarce, it matters:

| Mentors available | Overloaded mentors (independent picking) | Mean synergy, first-come | Mean synergy, optimal |
|---|---|---|---|
| 61 | 0 | 96.2 | 96.2 |
| 30 | 6.8 | 84.2 | 84.3 |
| 20 | 7.6 | 76.4 | 85.1 |
| 15 | 8.6 | 73.8 | 86.5 |
| 10 | 7.8 | 67.9 | **86.6** |

## 5. Make the state the source of truth

**Problem.** Two admins clicking Approve at once, or a retry after a timeout, must not create
two workspaces.

**Change.** Explicit state machines (`ophia-backend/state_machine.py`) for matches
(pending → approved | rejected), workspaces (active → completed | cancelled, milestones
30 → 60 → 90 in order) and provisioning. Approval runs in a Firestore transaction that
checks the match is still pending and creates the workspace with a deterministic ID.
Breaking a rule returns `409` with the reason.

**Result.** Approval is idempotent, and five concurrent approvals create exactly one
workspace. That test runs against Google's real Firestore emulator in CI, not just the
in-memory fake.

Email, Drive and Calendar provisioning runs in the background after approval. Each step's
outcome is recorded (`partial` if some succeed) and can be retried, so a Google outage
can't lose an approval.

## 6. Fail closed, and keep the bill at zero

- Every change, and every action that spends Gemini calls, requires the admin key
  (`X-API-Key`, compared in constant time).
- If the server has no key configured, changes return `503` rather than being open.
- Anonymous callers only read stored suggestions, so nobody can run up costs.
- The public demo is a static snapshot of real output on Streamlit Community Cloud: no
  cloud calls, no cost.

## 7. Tests that can fail

239 tests: 230 unit tests with fakes for Firestore, Vertex AI and Google Workspace, and 9
integration tests on the Firestore emulator. CI runs both on Python 3.11 and 3.12.

After writing the race-condition and auth tests, I re-introduced the original bugs to check
the tests caught them (mutation testing by hand). The race test initially *couldn't* fail,
so a delay was injected to force the interleaving. The auth check found a real **fail-open**
path when no key was configured, which is now fixed and tested.

---

## Full evaluation results

| Question | Method | Result |
|---|---|---|
| Does the score separate good from bad matches? | 49 startups; the intended mentor vs random mentors (`eval_scoring.py`) | Random mentors: old 0–100 prompt **61**, rubric blend **36** |
| Does re-ranking pick the right mentor? | Same data; is the final pick the mentor written for that startup? | Embeddings alone **73%**, old prompt 76%, blend **86%** (ceiling 90%) |
| Does the AI agree with a human? | 40 pairs labelled blind, stratified across the score range (`eval_human.py`) | Spearman **0.91**, AUC good-vs-bad **1.0**, weighted kappa **0.85** |
| Which signal matters? | Same 40 labels | Gemini rubric ≫ embedding similarity (kappa 0.90 vs 0.52 overall, 0.80 vs 0.24 on hard cases) |
| Fix for the main error pattern | Domain gate, pre-registered, 20 fresh pairs labelled by a second person | Kappa **0.64 → 0.96**; 9 of 10 affected pairs judged bad |
| Does capacity-aware assignment help? | Mentor pool shrunk from 61 to 10 (`eval_assignment.py`) | Mean synergy **87 optimal vs 68 first-come** at 10 mentors |

Reproduce with real Gemini calls:

```bash
python ophia-nlp/eval_scoring.py          # separation and top-1 accuracy
python ophia-nlp/eval_assignment.py       # capacity experiment
streamlit run ophia-nlp/label_app.py      # blind human labelling
python ophia-nlp/eval_human.py report     # agreement with the labels
```

## Limitations

- **Mentors are AI-generated**, not real people; startups come from the public YC dataset.
- **Human labels** come from two team members (not independent of the project) and total
  60 pairs, so differences smaller than about 0.05 kappa are within noise.
- **The approve/reject feedback loop** is wired up (`eval_human.py report` reads real
  decisions) but has no real admin decisions yet.
- **Workspace provisioning** (Gmail, Drive, Calendar) is tested against fakes only; it has
  not been run against real Google accounts.
- **"Synergy" is OPHIA's own score.** The assignment experiment shows the solver optimises
  it, not that people would prefer every assignment.
