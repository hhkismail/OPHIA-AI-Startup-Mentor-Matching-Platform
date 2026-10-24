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

# Demo mode unless a test opts in; must be set before api_client is imported
os.environ["OPHIA_API_URL"] = ""


class NoNetwork(RuntimeError):
    pass


def _no_network(*args, **kwargs):
    raise NoNetwork("network access is disabled in tests — patch in a fake")


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    import ai_engine
    import database

    monkeypatch.setattr(ai_engine, "get_client", _no_network)
    monkeypatch.setattr(ai_engine, "_get_db", _no_network)
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
         "industry_tags": ["Biotech"], "status": "Available", "bio_embedding": unit([0.9, 0.1, 0])},
        {"name": "Ms Pay", "title": "Banking head", "bio": "Banking", "skills": ["Payments"],
         "industry_tags": ["Fintech"], "status": "Available", "bio_embedding": unit([0.1, 0.9, 0])},
        {"name": "Mr Farm", "title": "Logistics COO", "bio": "Logistics", "skills": ["Supply chain"],
         "industry_tags": ["Retail"], "status": "Available", "bio_embedding": unit([0, 0.2, 0.9])},
        {"name": "Generalist", "title": "Advisor", "bio": "Everything", "skills": [],
         "industry_tags": [], "status": "Available", "bio_embedding": unit([1, 1, 1])},
    ]
