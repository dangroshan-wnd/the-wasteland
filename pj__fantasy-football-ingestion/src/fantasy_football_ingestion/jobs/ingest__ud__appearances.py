import json
import time
from pathlib import Path

import requests
from psycopg2.extras import Json
from tqdm import tqdm

from fantasy_football_ingestion.database import connect_to_db
from fantasy_football_ingestion.paths import SAMPLES_DIR
from fantasy_football_ingestion.underdog import scoring_types, slates

# -------------------------
# Model Notes
# -------------------------

# One API call per slate; upserts refresh ADP/scores on re-run. No auth required. Runs very quickly (full re-load ~1 minute)

# -------------------------
# Standard Toggles
# -------------------------

SLEEP_SECONDS = 5
REQUEST_TIMEOUT = 30
TEST_MODE = False
TEST_MODE_RECORD_LIMIT = 5

# -------------------------
# Source Toggles
# -------------------------

SLATE_FILTER_ENABLED = False
# Match slates where slate_name contains any of these substrings (e.g. "2026" → LIKE '%2026%')
SLATE_NAME_CONTAINS = [
    "2026",
]

# -------------------------
# Routing
# -------------------------

SAMPLE_JSON_PATH = SAMPLES_DIR / f"sample__{Path(__file__).stem}.json"

# -------------------------
# Defined Functions
# -------------------------


def get_scoring_types_to_run():
    return scoring_types


def get_slates_to_run():
    if not SLATE_FILTER_ENABLED:
        return slates
    if not SLATE_NAME_CONTAINS:
        raise ValueError("SLATE_FILTER_ENABLED is True but SLATE_NAME_CONTAINS is empty")

    filtered = [
        s for s in slates if any(substr in s["slate_name"] for substr in SLATE_NAME_CONTAINS)
    ]
    if not filtered:
        print(f"⚠️ No slates matched SLATE_NAME_CONTAINS: {SLATE_NAME_CONTAINS}")
    return filtered


def fetch_appearances_for_slate(slate, scoring_type_id):
    url = (
        f"https://stats.underdogfantasy.com/v1/slates/{slate['id']}"
        f"/scoring_types/{scoring_type_id}/appearances"
    )
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as e:
        print(f"⚠️ Network error for slate {slate['slate_name']}: {e}")
        return None
    if resp.status_code != 200:
        print(f"❌ Error {resp.status_code} for slate {slate['slate_name']}")
        return None
    try:
        appearances = resp.json().get("appearances", [])
        return [
            a
            for a in appearances
            if isinstance(a, dict)
            and (a.get("projection") or {}).get("scoring_type_id") == scoring_type_id
        ]
    except Exception as e:
        print(f"⚠️ Exception parsing appearances for slate {slate['slate_name']}: {e}")
        return None


def collect_appearances(slates_to_run, scoring_types_to_run, conn=None, *, record_limit=None):
    slates_subset = slates_to_run[:record_limit] if record_limit else slates_to_run
    all_appearances = []
    upserted = 0

    try:
        for scoring_type in scoring_types_to_run:
            desc = f"Fetching appearances ({scoring_type['scoring_type_name']})"
            for slate in tqdm(slates_subset, desc=desc, unit="slate"):
                appearances = fetch_appearances_for_slate(slate, scoring_type["id"])
                if appearances is None:
                    continue
                if appearances:
                    pairs = [(a, slate["id"]) for a in appearances]
                    if conn is not None:
                        upserted += upsert_appearances(conn, pairs)
                    else:
                        all_appearances.extend(pairs)
                time.sleep(SLEEP_SECONDS)
    except KeyboardInterrupt:
        print("\n🛑 Interrupted by user — keeping data fetched so far.")
        return all_appearances, upserted

    return all_appearances, upserted


def upsert_appearances(conn, appearances):
    if not appearances:
        return 0

    count = 0
    with conn.cursor() as cur:
        for appearance, slate_id in appearances:
            cur.execute(
                """
                INSERT INTO landing.ud_appearances (payload, slate_id)
                VALUES (%s, %s)
                ON CONFLICT ((payload->>'id')) DO UPDATE SET
                    payload = EXCLUDED.payload,
                    slate_id = EXCLUDED.slate_id,
                    ingested_at = NOW()
                """,
                (Json(appearance), slate_id),
            )
            count += cur.rowcount
    conn.commit()
    return count


def write_sample_json(appearances):
    SAMPLE_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    payloads = [appearance for appearance, _slate_id in appearances]
    with SAMPLE_JSON_PATH.open("w") as f:
        json.dump(payloads, f, indent=2)
    print(f"📄 Wrote {len(payloads)} appearances to {SAMPLE_JSON_PATH}")


def main():
    slates_to_run = get_slates_to_run()
    scoring_types_to_run = get_scoring_types_to_run()

    if SLATE_FILTER_ENABLED:
        patterns = ", ".join(repr(p) for p in SLATE_NAME_CONTAINS)
        names = ", ".join(s["slate_name"] for s in slates_to_run)
        print(
            f"🎯 Slate filter enabled — name contains any of [{patterns}] ({len(slates_to_run)}): {names}"
        )

    scoring_names = ", ".join(s["scoring_type_name"] for s in scoring_types_to_run)
    print(f"📊 Scoring types ({len(scoring_types_to_run)}): {scoring_names}")

    if TEST_MODE:
        appearances, _upserted = collect_appearances(
            slates_to_run, scoring_types_to_run, record_limit=TEST_MODE_RECORD_LIMIT
        )
        if appearances:
            write_sample_json(appearances)
        print(f"\n✅ Done. {len(appearances)} appearances written to sample file.")
        return

    conn = connect_to_db()
    _appearances, upserted = collect_appearances(slates_to_run, scoring_types_to_run, conn=conn)
    print(f"\n✅ Done. {upserted} rows upserted.")


if __name__ == "__main__":
    main()
