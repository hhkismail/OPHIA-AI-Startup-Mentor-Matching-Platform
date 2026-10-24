# seed_db.py
# Loads mentors + startups into Firestore.
# Clears the 'mentors' and 'startups' collections first, so re-running is safe
# (no duplicates). It does NOT touch 'active_entities' (approved matches).
#
# Sources:
#   startups → ophia-nlp/output/startups_embedded.json (from embed_data.py),
#              falling back to 3 built-in sample startups
#   mentors  → ophia-data/data/mentors.json (curated)
#              + ophia-nlp/output/mentors_embedded.json if present
# Any record without an embedding is embedded here, so matching works.
#
# Run from the repo root:  python ophia-data/seed_db.py

import sys
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
sys.path.insert(0, str(REPO_ROOT / "ophia-nlp"))

from database import get_db          # noqa: E402
from ai_engine import get_embedding  # noqa: E402

CURATED_MENTORS = HERE / "data" / "mentors.json"
PIPELINE_MENTORS = REPO_ROOT / "ophia-nlp" / "output" / "mentors_embedded.json"
PIPELINE_STARTUPS = REPO_ROOT / "ophia-nlp" / "output" / "startups_embedded.json"


def _load_json(path: Path) -> list:
    if path.is_file() and path.stat().st_size > 10:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return []


def _slug(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name.lower()).strip("_")[:50]


def _ensure_embedding(record: dict, vec_field: str, text_field: str) -> bool:
    if not record.get(vec_field):
        record[vec_field] = get_embedding(record.get(text_field, ""))
    return bool(record[vec_field])


def clear_collection(db, collection_name: str):
    print(f"[seed_db] Clearing existing '{collection_name}' collection...")
    count = 0
    batch = db.batch()
    for doc in db.collection(collection_name).stream():
        batch.delete(doc.reference)
        count += 1
        if count % 400 == 0:
            batch.commit()
            batch = db.batch()
    batch.commit()
    print(f"[seed_db] Deleted {count} existing documents from '{collection_name}'")


def write_collection(db, collection_name: str, records: list, name_field: str):
    clear_collection(db, collection_name)
    batch = db.batch()
    for i, record in enumerate(records, 1):
        batch.set(db.collection(collection_name).document(_slug(record[name_field])), record)
        # Firestore batch limit is 500 — commit every 400 to be safe
        if i % 400 == 0:
            batch.commit()
            batch = db.batch()
    batch.commit()
    print(f"[seed_db] ✅ Seeded {len(records)} {collection_name} into Firestore")


def load_mentors() -> list:
    mentors, seen = [], set()
    for m in _load_json(CURATED_MENTORS) + _load_json(PIPELINE_MENTORS):
        if m.get("name") in seen:
            continue
        seen.add(m["name"])
        if _ensure_embedding(m, "bio_embedding", "bio"):
            mentors.append(m)
        else:
            print(f"  [seed_db] ⚠️  Skipping mentor without embedding: {m['name']}")
    return mentors


def load_startups() -> list:
    startups = _load_json(PIPELINE_STARTUPS)
    if startups:
        print(f"[seed_db] Using {PIPELINE_STARTUPS.name}")
    else:
        print("[seed_db] No pipeline output found — using sample startups")
        startups = get_sample_startups()

    kept = []
    for s in startups:
        if _ensure_embedding(s, "description_embedding", "description"):
            kept.append(s)
        else:
            print(f"  [seed_db] ⚠️  Skipping startup without embedding: {s['company_name']}")
    return kept


def get_sample_startups() -> list:
    """
    Fallback sample startups if the pipeline hasn't been run.
    Matches the mock data already in Anna's UI.
    """
    return [
        {
            "company_name": "DataShield",
            "description": "AI-powered fraud detection and cybersecurity platform for fintech companies.",
            "batch": "W23",
            "status": "Active",
            "industry_tags": ["AI Security", "Fintech", "B2B"],
            "country": "Malaysia",
            "founders": [{"name": "Ahmad Faris", "bio": "Ex-Google security engineer"}],
            "website": None,
            "is_active": True,
            "description_embedding": None
        },
        {
            "company_name": "GreenLedger",
            "description": "ESG compliance and carbon tracking platform for enterprises in Southeast Asia.",
            "batch": "S23",
            "status": "Active",
            "industry_tags": ["ESG", "RegTech", "Climate Tech"],
            "country": "Singapore",
            "founders": [{"name": "Mei Lin Tan", "bio": "Former sustainability consultant"}],
            "website": None,
            "is_active": True,
            "description_embedding": None
        },
        {
            "company_name": "MediCore AI",
            "description": "Clinical ML platform that predicts patient outcomes using electronic health records.",
            "batch": "W23",
            "status": "Active",
            "industry_tags": ["Health AI", "MedTech", "Deep Learning"],
            "country": "Malaysia",
            "founders": [{"name": "Dr. Aisha Rahman", "bio": "Medical doctor turned AI researcher"}],
            "website": None,
            "is_active": True,
            "description_embedding": None
        }
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# RUN
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Emoji in log lines would crash print() on a cp1252 Windows console
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("=" * 60)
    print("OPHIA — Firestore Database Seeder")
    print("=" * 60)
    print("WARNING: This will clear and re-seed the 'mentors' and 'startups' collections.")
    confirm = input("Type 'yes' to continue: ").strip().lower()

    if confirm != "yes":
        print("Cancelled.")
        sys.exit(0)

    db = get_db()
    print("[seed_db] ✅ Connected to Firestore")

    print("\n--- Seeding Mentors ---")
    write_collection(db, "mentors", load_mentors(), "name")

    print("\n--- Seeding Startups ---")
    write_collection(db, "startups", load_startups(), "company_name")

    print("\n" + "=" * 60)
    print("✅ Database seeded successfully!")
    print("Check your Firestore console to verify the data.")
    print("=" * 60)
