# OPHIA

[![CI](https://github.com/hhkismail/OPHIA-AI-Startup-Mentor-Matching-Platform/actions/workflows/ci.yml/badge.svg)](https://github.com/hhkismail/OPHIA-AI-Startup-Mentor-Matching-Platform/actions/workflows/ci.yml)

AI mentor matching for startup accelerator programmes.

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
| `ophia-backend/` | FastAPI server: `GET /api/linkages`, `POST /api/linkages/approve`, `GET /api/workspaces`, `/api/startups`, `/api/mentors`, `/api/health`. Docs at `/docs`. |
| `ophia-frontend/` | Streamlit admin dashboard. Uses the backend when `OPHIA_API_URL` is set, otherwise mock data. |
| `models.py` | Shared Pydantic schemas. |

---

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

---

## Team

| Member | Role |
|---|---|
| Anna | Frontend & UI |
| Fitri | NLP Data Pipeline |
| Ismail | Backend & State Machine |
| Razin | Linkage Scoring & Data |
