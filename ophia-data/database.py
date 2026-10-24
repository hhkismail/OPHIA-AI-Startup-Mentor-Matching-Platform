# database.py
# Fitri's Firestore CRUD operations
# Razin imports these functions directly into his API endpoints

import os
import datetime
from pathlib import Path
import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv
from typing import Optional

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
    Razin calls this in his GET /api/startups endpoint.
    
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
    Used by Isma's matching engine.
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


def get_startup_by_name(company_name: str) -> Optional[dict]:
    """
    Fetches a single startup by company name.
    Returns the startup dict, or None if not found.
    """
    db = get_db()
    docs = (
        db.collection("startups")
        .where("company_name", "==", company_name)
        .limit(1)
        .stream()
    )
    for doc in docs:
        return doc.to_dict()
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# MENTOR FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def get_all_mentors() -> list:
    """
    Fetches all mentors from Firestore.
    Razin calls this in his GET /api/mentors endpoint.
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
    Used by Isma's matching engine.
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


def get_mentor_by_name(mentor_name: str) -> Optional[dict]:
    """
    Fetches a single mentor by name.
    Returns the mentor dict, or None if not found.
    """
    db = get_db()
    docs = (
        db.collection("mentors")
        .where("name", "==", mentor_name)
        .limit(1)
        .stream()
    )
    for doc in docs:
        return doc.to_dict()
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# ACTIVE ENTITIES (Approved Matches / Workspaces)
# ═══════════════════════════════════════════════════════════════════════════════

def create_active_entity(startup_name: str, mentor_name: str, synergy: int) -> str:
    """
    Creates a new Active Entity in Firestore when admin approves a match.
    This is the 'Programmable Entity' — the 90-day tracked workspace record.
    
    Razin calls this from his POST /api/approve-entity endpoint.
    Returns the new document ID.
    
    Example:
        entity_id = create_active_entity("DataShield", "Ehtisham Raza", 96)
    """
    db = get_db()
    now = datetime.datetime.now(datetime.timezone.utc)

    entity_data = {
        "startup_name": startup_name,
        "mentor_name": mentor_name,
        "synergy_score": synergy,
        "status": "In Progress",
        "workspace_name": f"Project {startup_name} × {mentor_name}",
        "created_at": firestore.SERVER_TIMESTAMP,
        "lifecycle_start": now.isoformat(),
        "lifecycle_end": (now + datetime.timedelta(days=90)).isoformat(),
        "active": True,
        "milestones": [
            {
                "day": 30,
                "objective": "Establish goals, align on tech stack, first check-in",
                "completed": False
            },
            {
                "day": 60,
                "objective": "Mid-term review — progress audit and course correction",
                "completed": False
            },
            {
                "day": 90,
                "objective": "Final evaluation and programme completion sign-off",
                "completed": False
            }
        ],
        # These get filled in by workspace_trigger.py after Google Workspace runs
        "drive_folder_url": None,
        "calendar_event_id": None,
        "intro_email_sent": False
    }

    # Auto-generate a document ID
    doc_ref = db.collection("active_entities").document()
    doc_ref.set(entity_data)

    print(f"[database] Created active entity: {entity_data['workspace_name']} → ID: {doc_ref.id}")
    return doc_ref.id


def get_all_active_entities() -> list:
    """
    Fetches all active workspace entities.
    Anna's UI sidebar 'Active Workspaces' reads from this.
    """
    db = get_db()
    docs = (
        db.collection("active_entities")
        .where("active", "==", True)
        .stream()
    )
    entities = []
    for doc in docs:
        data = doc.to_dict()
        data["doc_id"] = doc.id
        entities.append(data)
    print(f"[database] Fetched {len(entities)} active entities")
    return entities


def update_entity_workspace_urls(
    entity_id: str,
    drive_url: str = None,
    calendar_event_id: str = None,
    email_sent: bool = False
):
    """
    Updates an entity after workspace_trigger.py runs.
    Stores the Drive folder URL, Calendar event ID, and email status.
    
    Razin calls this after workspace automation completes.
    """
    db = get_db()
    update_data = {}

    if drive_url:
        update_data["drive_folder_url"] = drive_url
    if calendar_event_id:
        update_data["calendar_event_id"] = calendar_event_id
    if email_sent:
        update_data["intro_email_sent"] = True
    if not update_data:
        return

    db.collection("active_entities").document(entity_id).update(update_data)
    print(f"[database] Updated entity {entity_id} with workspace URLs")


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