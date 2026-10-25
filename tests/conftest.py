"""
Shared test setup.

Tests never touch Google Cloud: every network entry point (Vertex AI client,
Firestore) is replaced with one that fails loudly, and tests that need AI or
database behaviour patch in fakes explicitly.
"""

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
# Backend listed first so `import app` is the FastAPI app (the frontend also
# has an app.py; frontend tests load it by file path instead)
for sub in reversed(("ophia-backend", "ophia-nlp", "ophia-data", "ophia-frontend", "")):
    sys.path.insert(0, str(ROOT / sub))

# Set before any module loads the developer's .env (load_dotenv never
# overrides existing variables), so tests don't depend on local secrets.
os.environ["OPHIA_API_URL"] = ""          # demo mode unless a test opts in
os.environ["OPHIA_API_KEY"] = ""
os.environ["ADMIN_API_KEY"] = "test-admin-key"
# Local .env settings must not change test behaviour
os.environ["SUGGEST_NEW_MATCHES"] = "true"
os.environ["OPHIA_PENDING_LIMIT"] = "5"
# Ignore the committed ophia-frontend/snapshot.json; snapshot tests supply their own
os.environ["OPHIA_SNAPSHOT_PATH"] = str(Path(__file__).parent / "no-snapshot.json")
ADMIN_HEADERS = {"X-API-Key": "test-admin-key"}


class NoNetwork(RuntimeError):
    pass


def _no_network(*args, **kwargs):
    raise NoNetwork("network access is disabled in tests — patch in a fake")


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    import ai_engine
    import database

    monkeypatch.setattr(ai_engine, "get_client", _no_network)
    monkeypatch.setattr(database, "get_db", _no_network)


def unit(v):
    """Unit vector helper for building embeddings with known cosine similarity."""
    import numpy as np
    v = np.asarray(v, dtype=float)
    return list(v / np.linalg.norm(v))


@pytest.fixture
def startups():
    return [
        {"company_name": "BioCo", "description": "Drug discovery", "industry_tags": ["Biotech"],
         "country": "US", "description_embedding": unit([1, 0, 0])},
        {"company_name": "PayCo", "description": "Payments API", "industry_tags": ["Fintech"],
         "country": "BR", "description_embedding": unit([0, 1, 0])},
        {"company_name": "FarmCo", "description": "Group buying", "industry_tags": ["Retail"],
         "country": "ID", "description_embedding": unit([0, 0, 1])},
    ]


@pytest.fixture
def mentors():
    return [
        {"name": "Dr Bio", "title": "Comp bio VP", "bio": "Biology", "skills": ["Drug R&D"],
         "industry_tags": ["Biotech"], "status": "Available", "availability_hours": 6, "bio_embedding": unit([0.9, 0.1, 0])},
        {"name": "Ms Pay", "title": "Banking head", "bio": "Banking", "skills": ["Payments"],
         "industry_tags": ["Fintech"], "status": "Available", "availability_hours": 6, "bio_embedding": unit([0.1, 0.9, 0])},
        {"name": "Mr Farm", "title": "Logistics COO", "bio": "Logistics", "skills": ["Supply chain"],
         "industry_tags": ["Retail"], "status": "Available", "availability_hours": 6, "bio_embedding": unit([0, 0.2, 0.9])},
        {"name": "Generalist", "title": "Advisor", "bio": "Everything", "skills": [],
         "industry_tags": [], "status": "Available", "availability_hours": 6, "bio_embedding": unit([1, 1, 1])},
    ]
