import json
import time
from pathlib import Path

import requests
from psycopg2.extras import Json
from tqdm import tqdm

from fantasy_football_ingestion.database import connect_to_db
from fantasy_football_ingestion.paths import SAMPLES_DIR
from fantasy_football_ingestion.underdog import load_ud_auth, slates

# -------------------------
# Model Notes
# -------------------------

# Lorge. Takes at least a few hours to pull w/ sleep.
# Same draft response also carries users[]; upserted into landing.ud_users for username joins.

# -------------------------
# Standard Toggles
# -------------------------

SLEEP_SECONDS = 4
REQUEST_TIMEOUT = 30
TEST_MODE = False
TEST_MODE_RECORD_LIMIT = 2

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


def get_headers(token):
    return {"Authorization": f"Bearer {token}", "User-Agent": "Mozilla/5.0"}


def get_draft_ids_from_db(conn, slate_ids):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT payload->>'id'
            FROM landing.ud_drafts
            WHERE payload->>'slate_id' = ANY(%s)
            ORDER BY payload->>'draft_at'
            """,
            (list(slate_ids),),
        )
        return [r[0] for r in cur.fetchall() if r[0] is not None]


def get_existing_draft_ids(conn):
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT draft_id FROM landing.ud_draft_entries")
            return {r[0] for r in cur.fetchall() if r[0] is not None}
    except Exception as e:
        print(f"⚠️ Couldn't query landing.ud_draft_entries, proceeding with full scrape: {e}")
        return set()


def fetch_full_draft(draft_id, token):
    url = f"https://api.underdogfantasy.com/v2/drafts/{draft_id}"
    try:
        resp = requests.get(url, headers=get_headers(token), timeout=REQUEST_TIMEOUT)
    except requests.RequestException as e:
        print(f"⚠️ Network error on draft {draft_id}: {e}")
        return None
    if resp.status_code == 401:
        print(f"🛑 Auth failed on draft {draft_id} (401 Unauthorized). Token likely expired.")
        return "unauthorized"
    if resp.status_code != 200:
        print(f"⚠️ Skipped draft {draft_id} (status: {resp.status_code})")
        return None
    return resp.json()


def extract_entries_from_draft(raw):
    return [e for e in raw.get("draft", {}).get("draft_entries", []) if isinstance(e, dict)]


def extract_users_from_draft(raw):
    return [u for u in raw.get("draft", {}).get("users", []) if isinstance(u, dict)]


def collect_draft_entries(token, draft_ids, conn=None, *, record_limit=None):
    ids_to_run = draft_ids[:record_limit] if record_limit else draft_ids
    all_entries = []
    all_users = []
    inserted = 0
    users_upserted = 0

    try:
        for draft_id in tqdm(ids_to_run, desc="Fetching entries", unit="draft"):
            raw = fetch_full_draft(draft_id, token)
            if raw == "unauthorized":
                return all_entries, all_users, inserted, users_upserted, True
            if raw:
                entries = [(e, draft_id) for e in extract_entries_from_draft(raw)]
                users = extract_users_from_draft(raw)
                if conn is not None:
                    inserted += insert_draft_entries(conn, entries)
                    users_upserted += upsert_users(conn, users)
                else:
                    all_entries.extend(entries)
                    all_users.extend(users)

            time.sleep(SLEEP_SECONDS)
    except KeyboardInterrupt:
        print("\nInterrupted by user — keeping data fetched so far.")
        return all_entries, all_users, inserted, users_upserted, False

    return all_entries, all_users, inserted, users_upserted, False


def insert_draft_entries(conn, entries):
    if not entries:
        return 0

    inserted = 0
    with conn.cursor() as cur:
        for entry, draft_id in entries:
            cur.execute(
                """
                INSERT INTO landing.ud_draft_entries (payload, draft_id)
                VALUES (%s, %s)
                ON CONFLICT ((payload->>'id')) DO NOTHING
                """,
                (Json(entry), draft_id),
            )
            inserted += cur.rowcount
    conn.commit()
    return inserted


def upsert_users(conn, users):
    if not users:
        return 0

    upserted = 0
    with conn.cursor() as cur:
        for user in users:
            cur.execute(
                """
                INSERT INTO landing.ud_users (payload)
                VALUES (%s)
                ON CONFLICT ((payload->>'id')) DO UPDATE SET
                    payload = EXCLUDED.payload,
                    ingested_at = NOW()
                """,
                (Json(user),),
            )
            upserted += cur.rowcount
    conn.commit()
    return upserted


def write_sample_json(entries):
    SAMPLE_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    payloads = [entry for entry, _draft_id in entries]
    with SAMPLE_JSON_PATH.open("w") as f:
        json.dump(payloads, f, indent=2)
    print(f"📄 Wrote {len(payloads)} draft entries to {SAMPLE_JSON_PATH}")


def main():
    auth = load_ud_auth()
    token = auth["auth_token"]
    slates_to_run = get_slates_to_run()
    slate_ids = {s["id"] for s in slates_to_run}

    if SLATE_FILTER_ENABLED:
        patterns = ", ".join(repr(p) for p in SLATE_NAME_CONTAINS)
        names = ", ".join(s["slate_name"] for s in slates_to_run)
        print(
            f"🎯 Slate filter enabled — name contains any of [{patterns}] ({len(slates_to_run)}): {names}"
        )

    conn = connect_to_db()
    draft_ids = get_draft_ids_from_db(conn, slate_ids)
    print(f"📋 {len(draft_ids)} draft(s) in landing.ud_drafts for selected slates")

    existing_draft_ids = get_existing_draft_ids(conn)
    draft_ids = [d for d in draft_ids if d not in existing_draft_ids]
    print(f"🔁 {len(draft_ids)} draft(s) remaining after skipping already-ingested")

    if TEST_MODE:
        entries, users, _inserted, _users_upserted, unauthorized = collect_draft_entries(
            token, draft_ids, record_limit=TEST_MODE_RECORD_LIMIT
        )
        if entries:
            write_sample_json(entries)
        if unauthorized:
            print(
                f"Stopping pull due to expired token. "
                f"{len(entries)} draft entries and {len(users)} users saved to sample file."
            )
            return
        print(
            f"\nDone. {len(entries)} draft entries and {len(users)} users written to sample file."
        )
        return

    _entries, _users, inserted, users_upserted, unauthorized = collect_draft_entries(
        token, draft_ids, conn=conn
    )
    if unauthorized:
        print(
            f"Stopping pull due to expired token. "
            f"{inserted} entries inserted, {users_upserted} users upserted before exit."
        )
        return

    print(f"\nDone. {inserted} entries inserted, {users_upserted} users upserted.")


if __name__ == "__main__":
    main()
