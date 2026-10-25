# database.py
# Firestore connection and reads of the seeded startups and mentors.
# Matches and workspaces are handled by ophia-backend/repository.py.

import os
from pathlib import Path
import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent

# Load environment variables
load_dotenv(REPO_ROOT / ".env")

# ── Initialize Firebase App ───────────────────────────────────────────────────
# Only initialize once (prevents duplicate app error)

# Relative paths in .env are relative to the repo root, not the current folder
CREDENTIALS_PATH = REPO_ROOT / os.getenv(
    "FIREBASE_CREDENTIALS_PATH",
    "./ophia-data/credentials/firebase-adminsdk.json"
)

def get_db():
    """
    Returns an initialized Firestore client.
    Safe to call multiple times — only initializes Firebase once.
    Uses the service-account file if present, otherwise Application Default
    Credentials (`gcloud auth application-default login`) + GCP_PROJECT_ID.
    """
    if not firebase_admin._apps:
        if CREDENTIALS_PATH.is_file():
            firebase_admin.initialize_app(credentials.Certificate(str(CREDENTIALS_PATH)))
        else:
            firebase_admin.initialize_app(
                credentials.ApplicationDefault(),
                {"projectId": os.getenv("GCP_PROJECT_ID")},
            )
    return firestore.client()


# ═══════════════════════════════════════════════════════════════════════════════
# STARTUP FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def get_all_startups() -> list:
    """
    Fetches all startups from Firestore.
    Returns a list of startup dicts.
    """
    db = get_db()
    docs = db.collection("startups").stream()
    startups = []
    for doc in docs:
        data = doc.to_dict()
        data["doc_id"] = doc.id
        startups.append(data)
    print(f"[database] Fetched {len(startups)} startups")
    return startups


def get_active_startups() -> list:
    """
    Fetches only startups where is_active = True.
    """
    db = get_db()
    docs = (
        db.collection("startups")
        .where("is_active", "==", True)
        .stream()
    )
    startups = [doc.to_dict() for doc in docs]
    print(f"[database] Fetched {len(startups)} active startups")
    return startups


# ═══════════════════════════════════════════════════════════════════════════════
# MENTOR FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def get_all_mentors() -> list:
    """
    Fetches all mentors from Firestore.
    """
    db = get_db()
    docs = db.collection("mentors").stream()
    mentors = []
    for doc in docs:
        data = doc.to_dict()
        data["doc_id"] = doc.id
        mentors.append(data)
    print(f"[database] Fetched {len(mentors)} mentors")
    return mentors


def get_available_mentors() -> list:
    """
    Fetches only mentors where status = 'Available'.
    """
    db = get_db()
    docs = (
        db.collection("mentors")
        .where("status", "==", "Available")
        .stream()
    )
    mentors = [doc.to_dict() for doc in docs]
    print(f"[database] Fetched {len(mentors)} available mentors")
    return mentors


# ═══════════════════════════════════════════════════════════════════════════════
# QUICK TEST — run this file directly to confirm Firestore works
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=== Testing Firestore connection ===")
    db = get_db()
    print("Connected to Firestore successfully")

    # Write a test document
    test_ref = db.collection("_connection_test").document("ping")
    test_ref.set({"status": "ok", "message": "Firestore is connected"})
    print("Write test passed")

    # Read it back
    doc = test_ref.get()
    print(f"Read test passed: {doc.to_dict()}")

    # Clean up
    test_ref.delete()
    print("Delete test passed")
    print("=== All Firestore tests passed ===")