# OPHIA

[![CI](https://github.com/hhkismail/OPHIA-AI-Startup-Mentor-Matching-Platform/actions/workflows/ci.yml/badge.svg)](https://github.com/hhkismail/OPHIA-AI-Startup-Mentor-Matching-Platform/actions/workflows/ci.yml)

AI mentor matching for startup accelerator programmes: embeddings shortlist mentors,
Gemini grades each pair against a rubric, an optimiser assigns mentors within their
capacity, and an admin approves through an authenticated API that starts a tracked
90-day mentorship.

**[▶ Live demo](https://ophia-mentor-match.streamlit.app/)** (a snapshot of real output; try approving and rejecting)

![Matches page: suggested startup–mentor pairs with scores, grades and approve/reject](docs/screenshots/matches.png)

Built at **GDG KL Build With AI 2026 (MyHack)** for the Cradle Fund challenge *"Automating
Ecosystem Linkages Instead of Manual Coordination"*, then rebuilt on this fork. Not
affiliated with Cradle Fund.

**My role.** Team role was Backend & State Machine. At the hackathon I built the embedding
pipeline, the AI matching engine and the FastAPI backend. Afterwards I rebuilt the project
on my own fork: lifecycle state machine, auth, capacity-aware assignment, evaluation
against human labels, tests and CI, and deployment.

---

## Results at a glance

| | Hackathon approach¹ | Now |
|---|---|---|
| Score given to a **random** (wrong) mentor | 61 / 100 | **36** / 100 |
| Right mentor picked for a startup | 76% | **86%** (embeddings alone: 73%, ceiling 90%) |
| Agreement with a human, 40 blind-labelled pairs | not measured | Spearman **0.91**, weighted kappa **0.85** |
| Concurrent approvals of one match | no state, no checks | exactly one workspace (Firestore transaction, tested on the emulator) |
| Popular mentors overloaded when mentors are scarce | 7–9 | **0** (mean synergy 87 vs 68 first-come, 10 mentors) |
| Tests | none | 239 (230 unit + 9 on the Firestore emulator), CI on every push |

¹ Scores measured by re-running the hackathon's single 0–100 Gemini prompt on the same data.

---

## The problem

Accelerator administrators match startups to mentors by hand: read every profile, guess a
fit, email both sides, set up a shared folder, book a kick-off, then chase progress.
Nothing is reused between cohorts and nobody can say whether the matches were good.

## How it works

```
 YC startups ─┐
              ├─► embed (Vertex AI) ─► Firestore
 mentors ─────┘                            │
                                           ▼
 ┌──────────── for every unmatched startup ─────────────┐
 │ 1. Shortlist  top-3 mentors by cosine similarity     │
 │ 2. Grade      Gemini rubric: domain / need / market  │
 │ 3. Blend      0.4 × similarity pct + 0.6 × rubric    │
 │ 4. Gate       wrong domain (≤ 2/5) → capped at 49     │
 └──────────────────────────┬───────────────────────────┘
                            ▼
 5. Assign   Hungarian algorithm across all startups, within each mentor's hours
                            ▼
 6. Review   admin approves / rejects in the dashboard (API key required)
                            ▼
 7. Run      90-day workspace, milestones 30 → 60 → 90; email, Drive folder and
             Calendar kick-off provisioned in the background
```

**1. Shortlist.** Each startup and mentor is embedded with `text-embedding-004`. Raw cosine
similarity bunches between 0.3 and 0.7, so it is converted to a percentile against typical
pairs before use.

**2. Grade.** Gemini grades each shortlisted pair on three criteria, 1–5, each with written
anchors for what every score means. It writes its reasoning before the scores, runs at
temperature 0, and results are cached per prompt so a pair is never paid for twice.

**3–4. Blend and gate.** The rubric carries most of the weight because it agrees with
people far better than similarity does (below). Most remaining errors were mentors from the
wrong industry scoring "OK" on generic skills, so a domain gate caps them below the
"possible match" line.

**5. Assign.** Picking each startup's favourite independently overloads popular mentors.
OPHIA solves all startups at once: mentor slots (monthly hours ÷ 3) are columns of a cost
matrix, plus an "unassigned" column per startup, so a startup with only weak options is
left for a human rather than given a bad mentor.

**6–7. Lifecycle.** Matches, workspaces and provisioning each follow an explicit state
machine; anything else is rejected with `409` and a reason.

```
Match:         pending ──approve──► approved (creates a workspace)
                  └─────reject───► rejected (never suggested again)

Workspace:     active ──day-90 milestone done──► completed
                  └──────────cancel────────────► cancelled

Provisioning:  queued ──► succeeded | partial | skipped | failed ──retry──► queued
```

---

## Engineering decisions

**Measure the scorer before tuning it.** The hackathon version asked Gemini for a 0–100
score. Evaluated properly, it gave *random* mentors 61 on average, so the score barely
separated good from bad. Replacing it with a three-criterion rubric blended with
similarity brought random mentors down to 36 and raised top-1 accuracy from 76% to 86%.

**Don't grade the AI with its own answers.** The first evaluation used mentors that Gemini
had generated *for* each startup as the right answer, which is circular. So I built a blind
labelling app (AI score hidden, pairs sampled evenly across the score range) and measured
agreement with people instead.

**Pre-register the fix.** The human labels showed one main error pattern (wrong-industry
mentors scored as OK). I proposed the domain gate and committed its pass mark *before* a
second person labelled 20 fresh pairs
([`91afa6c`](https://github.com/hhkismail/OPHIA-AI-Startup-Mentor-Matching-Platform/commit/91afa6c)).
It passed (kappa 0.64 → 0.96, 9 of 10 affected pairs judged bad) and was adopted
([`fe98ee3`](https://github.com/hhkismail/OPHIA-AI-Startup-Mentor-Matching-Platform/commit/fe98ee3)).

**Make the state the source of truth.** Approving a match runs in a Firestore transaction
that checks the match is still pending and creates the workspace with a deterministic ID.
Five simultaneous approvals produce exactly one workspace, and that test runs against the
real Firestore emulator in CI, not just a mock. Approval is idempotent, so a retry after a
timeout is safe.

**Fail closed, and keep the bill at zero.** Every change and every Gemini call needs the
admin key; if the server has no key configured, changes return `503` instead of being
open. Anonymous visitors only read stored suggestions. The public demo is a static
snapshot, so nobody visiting it can spend money.

**Slow side effects don't block the request.** Email, Drive and Calendar run in the
background after approval, each step's result is recorded (`partial` if some succeed), and
an admin can retry. A Google outage can't lose an approval.

**Tests that can fail.** After writing the race-condition and auth tests I re-introduced
the original bugs to check the tests caught them. One check found a real fail-open path
when no key was set, which is now fixed and tested.

---

## Evaluation

![Evaluation page: agreement with human labels and the domain gate](docs/screenshots/evaluation-agreement.png)

| Question | Method | Result |
|---|---|---|
| Does the score separate good from bad matches? | 49 startups; the intended mentor vs random mentors (`eval_scoring.py`) | Random mentors: old 0–100 prompt **61**, rubric blend **36** |
| Does re-ranking pick the right mentor? | Same data; is the final pick the mentor written for that startup? | Embeddings alone **73%**, old prompt 76%, blend **86%** (ceiling 90%) |
| Does the AI agree with a human? | 40 pairs labelled blind, stratified across the score range (`eval_human.py`) | Spearman **0.91**, AUC good-vs-bad **1.0**, weighted kappa **0.85** |
| Which signal matters? | Same 40 labels | Gemini rubric ≫ embedding similarity (kappa 0.90 vs 0.52 overall, 0.80 vs 0.24 on hard cases); the 0.4 blend weight is within noise of the best |
| Fix for the main error pattern | Domain gate, **pre-registered**, tested on 20 fresh pairs labelled by a second person | Kappa **0.64 → 0.96**; 9 of 10 affected pairs judged bad → adopted |
| Does capacity-aware assignment help? | Mentor pool shrunk from 61 to 10 (`eval_assignment.py`) | No effect with 61 mentors (seeded ~1:1). With 10: independent picking overloads 7–9 mentors; mean synergy **87 optimal vs 68 first-come** |

![Evaluation page: score separation and capacity-aware assignment](docs/screenshots/evaluation-assignment.png)

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

---

## Screenshots

| Mentor directory | |
|---|---|
| ![Mentor directory with search, expertise filter and capacity](docs/screenshots/mentors.png) | Search, filter by expertise, sort; capacity is monthly hours ÷ 3 hours per mentorship. |

---

## Project layout

| Folder | What it does |
|---|---|
| `ophia-nlp/` | `embed_data.py` builds startups (YC CSV) and generated mentors with embeddings. `ai_engine.py` shortlists, grades and scores. `assignment.py` is the capacity-aware optimiser. `eval_*.py` and `label_app.py` are the evaluation. |
| `ophia-backend/` | FastAPI server (`app.py`), lifecycle rules (`state_machine.py`), storage (`repository.py`: Firestore with transactions, or in-memory for tests), response schemas (`schemas.py`). Interactive docs at `/docs`. |
| `ophia-data/` | `database.py` Firestore reads, `seed_db.py` loads data, `workspace_trigger.py` sends the intro email, creates the Drive folder and milestone doc, and books the Calendar kick-off. |
| `ophia-frontend/` | Streamlit admin dashboard: live backend, snapshot, or built-in sample data. |
| `tests/` | Unit tests (fakes for Firestore, Vertex AI and Workspace) and `integration/` tests on the Firestore emulator. |

**Stack:** Python, FastAPI, Pydantic, Streamlit, Vertex AI (`text-embedding-004`, Gemini
`gemini-3.1-flash-lite`), Firestore, SciPy, Gmail / Drive / Calendar APIs, GitHub Actions.

## API

| Endpoint | What it does |
|---|---|
| `GET /api/linkages?limit=5&refresh=false` | Pending suggestions. When they run low, an admin refresh suggests for all unmatched startups at once, assigned jointly within capacity |
| `POST /api/matches/{id}/approve` | Creates the workspace. Idempotent: approving twice returns the same workspace |
| `POST /api/matches/{id}/reject` | Optional `{"reason": "..."}` |
| `GET /api/matches?status=approved` | Every decision: the record of admin choices |
| `GET /api/workspaces` | All workspaces with milestones and provisioning status |
| `POST /api/workspaces/{id}/milestones/{day}/complete` | Next milestone; the last one completes the workspace |
| `POST /api/workspaces/{id}/cancel` | |
| `POST /api/workspaces/{id}/provision` | Retry email/Drive/Calendar after `partial`, `skipped` or `failed` |
| `GET /api/stats`, `/api/startups`, `/api/mentors`, `/api/health` | |

Every `POST`, and generating new suggestions, requires the admin key (`ADMIN_API_KEY`) in an
`X-API-Key` header, otherwise `401`. Lifecycle violations return `409` with the reason;
unknown IDs `404`; storage outages `503`.

## Running it

**Demo mode (no keys needed)**

```bash
cd ophia-frontend
pip install -r requirements.txt
streamlit run app.py
```

The dashboard picks its data source automatically: the live backend if `OPHIA_API_URL` is
set, otherwise `snapshot.json` (real exported output), otherwise built-in sample data.

**Live mode**

1. Copy `.env.example` to `.env` in the repo root and fill it in. Never commit `.env`.
2. Google Cloud login (Vertex AI + Firestore): `gcloud auth application-default login`
   (or put a Firebase service-account key at `ophia-data/credentials/firebase-adminsdk.json`).
3. `pip install -r ophia-backend/requirements.txt -r ophia-frontend/requirements.txt`
4. Build the data (optional; `seed_db.py` embeds anything missing): `cd ophia-nlp && python embed_data.py`
5. Load Firestore: `python ophia-data/seed_db.py`
6. Google Workspace login (once; needs an OAuth client at
   `ophia-data/credentials/workspace-credentials.json`): `python ophia-data/workspace_trigger.py`
7. Backend: `cd ophia-backend && uvicorn app:app --reload`
8. Frontend: set `OPHIA_API_URL="http://localhost:8000"` in `.env`, then `cd ophia-frontend && streamlit run app.py`

> If you change `EMBED_MODEL`, re-run steps 4–5: vectors from different models can't be compared.

**Public demo.** Streamlit Community Cloud runs `ophia-frontend/app.py` on
`ophia-frontend/snapshot.json`. It never calls Google Cloud. To refresh it:
`python ophia-frontend/export_snapshot.py` (reads Firestore, no Gemini calls), then commit
`snapshot.json`.

## Tests

```bash
pip install -r ophia-backend/requirements.txt -r ophia-frontend/requirements.txt -r requirements-dev.txt
ruff check .
pytest
```

Unit tests replace Firestore, Vertex AI and Google Workspace with fakes, so they need no
credentials or network. The integration tests in `tests/integration/` run the production
Firestore code against Google's emulator (they skip locally unless
`FIRESTORE_EMULATOR_HOST` is set). CI runs both on every push.

Match quality is measured separately, with real Gemini calls:

```bash
python ophia-nlp/eval_scoring.py          # separation and top-1 accuracy
python ophia-nlp/eval_assignment.py       # capacity experiment
streamlit run ophia-nlp/label_app.py      # blind human labelling
python ophia-nlp/eval_human.py report     # agreement with the labels
```

## Team

| Member | Hackathon role |
|---|---|
| Anna | Frontend & UI |
| Fitri | NLP Data Pipeline |
| Ismail | Backend & State Machine |
| Razin | Linkage Scoring & Data |
