# OPHIA
**Ontology-driven Programmable Hub for Innovation Administration**

> *"We aren't a dating app for startups. We are the autonomous operating system for ecosystem administrators."*

Built for **GDG KL Build With AI 2026 KL — MyHack** in response to the Cradle Fund problem statement: *Automating Ecosystem Linkages Instead of Manual Coordination.*

---

## The Problem

Ecosystem administrators manually verify participants, guess mentor matches, send emails one by one, and start from scratch every programme cycle. Nothing is reusable. Nothing is tracked. Nothing improves.

## The Solution

OPHIA is an AI-powered orchestration platform built for programme administrators. It matches startups to mentors using Vertex AI embeddings, explains every match with a Gemini-generated insight, and automates everything after approval — intro email, Drive workspace, Calendar invite — in one click.

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

---

## Team

| Member | Role |
|---|---|
| Anna | Frontend & UI |
| Fitri | NLP Data Pipeline |
| Ismail | Backend & State Machine |
| Razin | Linkage Scoring & Data |
