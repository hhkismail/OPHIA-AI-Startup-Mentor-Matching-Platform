# OPHIA

[![CI](https://github.com/hhkismail/OPHIA-AI-Startup-Mentor-Matching-Platform/actions/workflows/ci.yml/badge.svg)](https://github.com/hhkismail/OPHIA-AI-Startup-Mentor-Matching-Platform/actions/workflows/ci.yml)

AI mentor matching for startup accelerator programmes.

**[▶ Live demo](https://ophia-mentor-match.streamlit.app/)**: read-only snapshot of real output; see the *Evaluation* tab for how match quality was measured.

Built at **GDG KL Build With AI 2026 — MyHack** for the Cradle Fund challenge *"Automating Ecosystem Linkages Instead of Manual Coordination"*. Not affiliated with Cradle Fund.

---

## The Problem

Ecosystem administrators manually verify participants, guess mentor matches, send emails one by one, and start from scratch every programme cycle. Nothing is reusable. Nothing is tracked. Nothing improves.

## The Solution

OPHIA suggests the best mentor for each startup and explains why. Embeddings shortlist candidates, Gemini grades each one against a rubric, and the admin approves. Approval creates a 90-day workspace and can send the intro email, create a Drive folder and book a Calendar kick-off.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Streamlit |
| Backend | FastAPI |
| AI / Embeddings | Vertex AI (`EMBED_MODEL`, default `text-embedding-004`) |
| Language Model | Gemini (`GEN_MODEL`, default `gemini-3.1-flash-lite`) |
| Database | Google Cloud Firestore |
| Automation | Gmail API, Google Drive API, Google Calendar API |

## How it fits together

```
ophia-nlp/embed_data.py  ─► ophia-nlp/output/*.json ─► ophia-data/seed_db.py ─► Firestore
                                                                                   │
ophia-frontend (Streamlit) ◄──► ophia-backend/app.py (FastAPI) ◄── ophia-nlp/ai_engine.py
                                        │  on approve
                                        ▼
                         ophia-data/workspace_trigger.py (Gmail + Drive + Calendar)
```

| Folder | What it does |
|---|---|
| `ophia-nlp/` | `embed_data.py` builds startups (from the YC CSV) + AI-generated mentors with embeddings. `ai_engine.py` ranks mentors by cosine similarity and has Gemini score/explain the top matches. |
| `ophia-data/` | `database.py` Firestore CRUD, `seed_db.py` loads data into Firestore, `workspace_trigger.py` sends the intro email, creates the Drive folder + milestone doc, and books the Calendar kick-off. |
| `ophia-backend/` | FastAPI server (`app.py`), lifecycle rules (`state_machine.py`) and storage (`repository.py`: Firestore with transactions, or in-memory for tests). API below; interactive docs at `/docs`. |
| `ophia-frontend/` | Streamlit admin dashboard. Uses the backend when `OPHIA_API_URL` is set, otherwise mock data. |
| `models.py` | Shared Pydantic schemas. |

---

## Public demo (snapshot)

The public dashboard runs on Streamlit Community Cloud from `ophia-frontend/app.py` and
shows `ophia-frontend/snapshot.json`: real output exported from the live system (AI
suggestions with their Gemini grades). It is read-only and never calls Google Cloud, so
visitors cost nothing. The **Evaluation** tab shows how match quality was measured.

To refresh it after changes: `python ophia-frontend/export_snapshot.py` (reads Firestore
anonymously, so no Gemini calls), then commit `snapshot.json`.

The dashboard picks its data source automatically: the live backend if `OPHIA_API_URL` is
set, otherwise the snapshot if present, otherwise built-in sample data.

## Quick Start — demo mode (no keys needed)

```bash
cd ophia-frontend
pip install -r requirements.txt
streamlit run app.py
```

Opens at `localhost:8501` with mock data.

## Full setup — live mode

1. **Config:** copy `.env.example` to `.env` in the repo root and fill it in. Never commit `.env`.
2. **Google Cloud login** (Vertex AI + Firestore):
   `gcloud auth application-default login`
   (or put a Firebase service-account key at `ophia-data/credentials/firebase-adminsdk.json`).
3. **Install:** `pip install -r ophia-backend/requirements.txt -r ophia-frontend/requirements.txt`
4. **Build the data** (optional — `seed_db.py` embeds anything missing):
   `cd ophia-nlp && python embed_data.py`
5. **Load Firestore:** `python ophia-data/seed_db.py`
6. **Google Workspace login** (once — opens a browser; needs an OAuth client file at
   `ophia-data/credentials/workspace-credentials.json`): `python ophia-data/workspace_trigger.py`
7. **Run the backend:** `cd ophia-backend && uvicorn app:app --reload`
8. **Run the frontend:** set `OPHIA_API_URL="http://localhost:8000"` in `.env`, then
   `cd ophia-frontend && streamlit run app.py`

> If you change `EMBED_MODEL`, re-run steps 4–5: vectors from different models can't be compared.

## Lifecycle and API

```
Match:         pending ──approve──► approved (creates a workspace)
                  └─────reject───► rejected (that mentor is never suggested to that startup again)

Workspace:     active ──day-90 milestone done──► completed
                  └──────────cancel────────────► cancelled
               (milestones 30 → 60 → 90 must be completed in order)

Provisioning:  queued ──► succeeded | partial | skipped | failed ──retry──► queued
               (intro email + Drive folder + Calendar kick-off, run in the background)
```

| Endpoint | What it does |
|---|---|
| `GET /api/linkages?limit=5&refresh=false` | Pending suggestions. When they run low, all unmatched startups get suggestions at once, assigned jointly so no mentor goes over capacity (stored, so Gemini runs once per startup) |
| `POST /api/matches/{id}/approve` | Creates the workspace. Idempotent: approving twice returns the same workspace |
| `POST /api/matches/{id}/reject` | Optional `{"reason": "..."}` |
| `GET /api/matches?status=approved` | Every decision, i.e. the record of admin choices |
| `GET /api/workspaces` | All workspaces with milestones and provisioning status |
| `POST /api/workspaces/{id}/milestones/{day}/complete` | Next milestone; the last one completes the workspace |
| `POST /api/workspaces/{id}/cancel` | |
| `POST /api/workspaces/{id}/provision` | Retry email/Drive/Calendar after `partial`, `skipped` or `failed` |
| `GET /api/stats`, `/api/startups`, `/api/mentors`, `/api/health` | |

**Auth.** Every `POST`, and generating new suggestions, requires the admin key
(`ADMIN_API_KEY` in `.env`) in an `X-API-Key` header; otherwise `401`. Reads are public,
and an anonymous `GET /api/linkages` returns only stored suggestions, so visitors can't
run up Gemini costs. If the server has no key configured, changes are disabled (`503`)
rather than left open. The dashboard sends `OPHIA_API_KEY` from the server side; without
it, the dashboard is read-only.

Breaking a lifecycle rule returns `409 Conflict` with the reason; unknown IDs return `404`.
Approvals run in a Firestore transaction, so concurrent approvals of one match create one workspace.

## Tests

```bash
pip install -r ophia-backend/requirements.txt -r ophia-frontend/requirements.txt -r requirements-dev.txt
ruff check .
pytest
```

The tests replace Firestore, Vertex AI and Google Workspace with fakes, so they need no
credentials or network. CI runs them on every push (Python 3.11 and 3.12).

Match quality is measured separately with `python ophia-nlp/eval_scoring.py` (uses real
Gemini calls; results in `ophia-nlp/output/eval_results.json`).

**Human labels.** `eval_scoring.py` checks the AI against mentors the AI itself generated,
which is circular. To check it against a person instead:

```bash
python ophia-nlp/eval_human.py build      # 40 pairs, 8 per AI-score band (already built)
streamlit run ophia-nlp/label_app.py      # label each pair Good / OK / Bad, AI score hidden
python ophia-nlp/eval_human.py report     # agreement (Spearman, AUC, weighted kappa) + disagreements
```

---

## Evaluation results

| Question | Method | Result |
|---|---|---|
| Does the score separate good from bad matches? | 49 startups; intended mentor vs random mentors (`eval_scoring.py`) | Old 0-100 prompt: random mentors averaged **61**. Rubric + similarity blend: **36** |
| Does re-ranking pick the right mentor? | Same data; is the final pick the mentor generated for that startup? | Embeddings alone **73%**, old prompt 76%, blend **86%** (ceiling 90%) |
| Does the AI agree with a human? | 40 pairs labelled blind, stratified across the score range (`eval_human.py`) | Spearman **0.91**, AUC good-vs-bad **1.0**, weighted kappa **0.85** |
| Which signal matters? | Same 40 labels | Gemini rubric ≫ embedding similarity (kappa 0.90 vs 0.52 overall, 0.80 vs 0.24 on hard cases); the 0.4 blend weight is within noise of the best |
| Fix for the main error pattern | Domain gate (domain fit ≤ 2 → score capped at 49), **pre-registered**, tested on 20 fresh pairs labelled by a second person | Kappa **0.64 → 0.96**; 9 of 10 affected pairs judged bad → adopted |
| Does capacity-aware assignment help? | Mentor pool shrunk from 61 to 10 (`eval_assignment.py`) | No effect on the seeded 1:1 data. With scarce mentors, independent picking overloads 7-9 mentors; optimal vs first-come: mean synergy **87 vs 68** at 10 mentors |

**Limitations.** Mentors are AI-generated, not real people. Human labels come from two
team members (not independent of the project) and total 60 pairs, so differences
smaller than about 0.05 kappa are within noise. The approve/reject feedback loop is wired
up (`eval_human.py report`) but has no real decisions yet.

## Team

| Member | Role |
|---|---|
| Anna | Frontend & UI |
| Fitri | NLP Data Pipeline |
| Ismail | Backend & State Machine |
| Razin | Linkage Scoring & Data |
