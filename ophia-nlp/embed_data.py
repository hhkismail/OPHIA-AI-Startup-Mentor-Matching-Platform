"""
embed_data.py — OPHIA Data Pipeline

- Vertex AI (ADC)        → embeddings (billed to GCP credits)
- Gemini API key or ADC  → mentor generation

Config comes from the repo-root .env (GCP_PROJECT_ID, EMBED_MODEL, GEN_MODEL,
optional GEMINI_API_KEY). Never paste API keys into this file.

Run (from ophia-nlp/):
  gcloud auth application-default login
  python embed_data.py
"""

import os
import sys
import json
import ast
import time
from pathlib import Path

import pandas as pd
from google import genai
from google.genai import types

from ai_engine import (
    GEN_MODEL, get_embedding, get_gen_client, mentor_embedding_text, startup_embedding_text,
)

# Emoji in log lines would crash print() on a cp1252 Windows console
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── CONFIG ────────────────────────────────────────────────────────────────────
HERE            = Path(__file__).resolve().parent
SAMPLE_SIZE     = 50
MAX_RETRIES     = 3
CSV_PATH        = HERE / "data/raw/2023-07-13-yc-companies.csv"
OUT_STARTUPS    = HERE / "output/startups_embedded.json"
OUT_MENTORS     = HERE / "output/mentors_embedded.json"

# Generation: Gemini API key if provided (free tier), otherwise Vertex AI
_api_key = os.getenv("GEMINI_API_KEY")
gen_client = genai.Client(api_key=_api_key) if _api_key else get_gen_client()
print(f"✅ Generation via {'Gemini API key' if _api_key else 'Vertex AI'} ({GEN_MODEL})")


# ── STEP 1: LOAD & CLEAN STARTUP CSV ─────────────────────────────────────────
def load_startups(csv_path: Path, n: int = SAMPLE_SIZE) -> list[dict]:
    print(f"\n📂 Loading CSV from: {csv_path}")
    df = pd.read_csv(csv_path)

    df = df[
        (df["status"] == "Active") &
        (df["short_description"].notna()) &
        (df["country"].notna())
    ].copy()

    df = df.sample(n=min(n, len(df)), random_state=42).reset_index(drop=True)

    startups = []
    for _, row in df.iterrows():
        try:
            tags = ast.literal_eval(row["tags"]) if pd.notna(row["tags"]) else []
        except Exception:
            tags = []

        try:
            founder_names = ast.literal_eval(row["founders_names"]) if pd.notna(row["founders_names"]) else []
        except Exception:
            founder_names = []

        founders = [{"name": name, "bio": None, "linkedin": None, "twitter": None}
                    for name in founder_names]

        startup = {
            "company_name": str(row["company_name"]),
            "description": str(row["short_description"]),
            "long_description": str(row["long_description"]) if pd.notna(row["long_description"]) else None,
            "batch": str(row["batch"]) if pd.notna(row["batch"]) else "Unknown",
            "status": str(row["status"]),
            "industry_tags": tags[:5],
            "country": str(row["country"]),
            "founders": founders,
            "website": str(row["website"]) if pd.notna(row["website"]) else None,
            "is_active": True,
            "description_embedding": None
        }
        startups.append(startup)

    print(f"✅ Loaded {len(startups)} startups")
    return startups


# ── STEP 2: GENERATE MENTOR ──────────────────────────────────────────────────
MENTOR_GEN_PROMPT = """
You are generating a realistic mentor profile for an innovation ecosystem platform.

Given this startup:
- Name: {company_name}
- Description: {description}
- Industry Tags: {tags}
- Country: {country}

Generate ONE mentor who would be an excellent match. The mentor should have:
- Complementary industry expertise (not identical, but relevant)
- Real-sounding name and title (vary names across cultures and regions)
- A compelling 2-sentence bio mentioning their background and what they offer startups
- 3-5 specific skills relevant to this startup's stage and domain
- Availability of 4-10 hours per month
- A name that is NOT any of these already-used names: {used_names}

Respond ONLY with a valid JSON object with these exact keys:
{{
  "name": "string",
  "title": "string",
  "bio": "string (2 sentences)",
  "industry_tags": ["list", "of", "strings"],
  "skills": ["list", "of", "strings"],
  "availability_hours": integer,
  "linkedin": null,
  "status": "Available",
  "partnerships": 0,
  "bio_embedding": null
}}
Do not include any text outside the JSON object.
"""


def generate_mentor(startup: dict, used_names: set) -> dict | None:
    """Returns a generated mentor with a name not in used_names, or None after
    MAX_RETRIES failures.

    Never substitutes a placeholder mentor: identical placeholders all get the
    same embedding, which makes every startup match the same "mentor".
    Gemini tends to reuse the same few names, so used names go in the prompt.
    """
    prompt = MENTOR_GEN_PROMPT.format(
        company_name=startup["company_name"],
        description=startup["description"],
        tags=", ".join(startup["industry_tags"]),
        country=startup["country"],
        used_names=", ".join(sorted(used_names)) or "(none yet)",
    )
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = gen_client.models.generate_content(
                model=GEN_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.7,
                )
            )
            mentor = json.loads(response.text.strip())
            if not (mentor.get("name") and mentor.get("bio")):
                raise ValueError("response missing name/bio")
            if mentor["name"] in used_names:
                raise ValueError(f"duplicate name {mentor['name']!r}")
            return mentor
        except Exception as e:
            print(f"  ⚠️  Mentor gen attempt {attempt}/{MAX_RETRIES} failed for {startup['company_name']}: {e}")
            time.sleep(2 ** attempt)
    return None


# ── MAIN PIPELINE ─────────────────────────────────────────────────────────────
def run_pipeline():
    OUT_STARTUPS.parent.mkdir(exist_ok=True)

    startups = load_startups(CSV_PATH)
    kept_startups, mentors, seen_names = [], [], set()

    print(f"\n🤖 Generating mentors + embeddings for {len(startups)} startups...")
    print("   (~3-5 minutes total, free tier = 15 req/min)\n")

    for i, startup in enumerate(startups):
        print(f"  [{i+1}/{len(startups)}] {startup['company_name']}")

        print("    → Embedding startup description...")
        startup["description_embedding"] = get_embedding(startup_embedding_text(startup))
        if not startup["description_embedding"]:
            print("    ⚠️  Skipping startup (no embedding)")
            continue
        kept_startups.append(startup)

        mentor = generate_mentor(startup, seen_names)
        if mentor:
            print("    → Embedding mentor bio...")
            mentor["bio_embedding"] = get_embedding(mentor_embedding_text(mentor))
            if mentor["bio_embedding"]:
                mentors.append(mentor)
                seen_names.add(mentor["name"])

        # Rate limit: Gemini API free tier = 15 req/min, so ~4 sec between
        # iterations. Vertex AI (paid) doesn't need the wait.
        time.sleep(4 if _api_key else 0.5)

    if len(mentors) < len(startups) // 2:
        raise SystemExit(
            f"❌ Only {len(mentors)}/{len(startups)} mentors generated — check GEN_MODEL "
            "and your credentials. Nothing was saved."
        )

    with open(OUT_STARTUPS, "w", encoding="utf-8") as f:
        json.dump(kept_startups, f, indent=2)
    print(f"\n✅ Saved: {OUT_STARTUPS}")

    with open(OUT_MENTORS, "w", encoding="utf-8") as f:
        json.dump(mentors, f, indent=2)
    print(f"✅ Saved: {OUT_MENTORS}")

    print("\n🎉 Pipeline complete! Next: python ../ophia-data/seed_db.py")
    print(f"   Startups: {len(kept_startups)} | Mentors: {len(mentors)}")


if __name__ == "__main__":
    if not CSV_PATH.exists():
        raise FileNotFoundError(
            f"CSV not found at: {CSV_PATH}\n"
            f"Make sure the YC CSV is at ophia-nlp/data/raw/2023-07-13-yc-companies.csv"
        )
    run_pipeline()
