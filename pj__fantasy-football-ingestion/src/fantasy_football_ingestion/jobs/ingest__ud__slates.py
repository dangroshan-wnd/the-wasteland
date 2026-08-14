import json
import time
from pathlib import Path

import requests
from psycopg2.extras import Json
from tqdm import tqdm

from fantasy_football_ingestion.database import connect_to_db
from fantasy_football_ingestion.paths import SAMPLES_DIR
from fantasy_football_ingestion.underdog import slates

# -------------------------
# Model Notes
# -------------------------

# One API call per slate id; no auth required. Upserts refresh metadata on re-run.
# Master slate list lives in keys/ud_ingest_keys.py — add new slates there.

# -------------------------
# Standard Toggles
# -------------------------

SLEEP_SECONDS = 1
REQUEST_TIMEOUT = 30
TEST_MODE = False
TEST_MODE_RECORD_LIMIT = 3

# -------------------------
# Routing
# -------------------------

SAMPLE_JSON_PATH = SAMPLES_DIR / f"sample__{Path(__file__).stem}.json"
SLATE_URL = "https://stats.underdogfantasy.com/v1/slates/{slate_id}"

# -------------------------
# Defined Functions
# -------------------------


def get_slate_ids_to_run():
    if not slates:
        raise ValueError("slates is empty in keys/ud_ingest_keys.py — add at least one entry")
    return [s["id"] for s in slates]


def fetch_slate(slate_id):
    url = SLATE_URL.format(slate_id=slate_id)
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as e:
        print(f"Network error for slate {slate_id}: {e}")
        return None
    if resp.status_code != 200:
        print(f"Error {resp.status_code} for slate {slate_id}")
        return None
    try:
        slate = resp.json().get("slate")
        return slate if isinstance(slate, dict) else None
    except Exception as e:
        print(f"Exception parsing slate {slate_id}: {e}")
        return None


def collect_slates(slate_ids, conn=None, *, record_limit=None):
    ids_subset = slate_ids[:record_limit] if record_limit else slate_ids
    all_slates = []
    upserted = 0

    try:
        for slate_id in tqdm(ids_subset, desc="Fetching slates", unit="slate"):
            slate = fetch_slate(slate_id)
            if slate is None:
                continue
            if conn is not None:
                upserted += upsert_slates(conn, [slate])
            else:
                all_slates.append(slate)
            time.sleep(SLEEP_SECONDS)
    except KeyboardInterrupt:
        print("\nInterrupted by user — keeping data fetched so far.")
        return all_slates, upserted

    return all_slates, upserted


def upsert_slates(conn, slates):
    if not slates:
        return 0

    count = 0
    with conn.cursor() as cur:
        for slate in slates:
            cur.execute(
                """
                INSERT INTO landing.ud_slates (payload)
                VALUES (%s)
                ON CONFLICT ((payload->>'id')) DO UPDATE SET
                    payload = EXCLUDED.payload,
                    ingested_at = NOW()
                """,
                (Json(slate),),
            )
            count += cur.rowcount
    conn.commit()
    return count


def write_sample_json(slates):
    SAMPLE_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SAMPLE_JSON_PATH.open("w") as f:
        json.dump(slates, f, indent=2)
    print(f"Wrote {len(slates)} slates to {SAMPLE_JSON_PATH}")


def main():
    slate_ids = get_slate_ids_to_run()
    print(f"{len(slate_ids)} slate id(s) configured")

    if TEST_MODE:
        slates, _upserted = collect_slates(slate_ids, record_limit=TEST_MODE_RECORD_LIMIT)
        if slates:
            write_sample_json(slates)
        print(f"\nDone. {len(slates)} slates written to sample file.")
        return

    conn = connect_to_db()
    _slates, upserted = collect_slates(slate_ids, conn=conn)
    print(f"\nDone. {upserted} rows upserted.")


if __name__ == "__main__":
    main()
