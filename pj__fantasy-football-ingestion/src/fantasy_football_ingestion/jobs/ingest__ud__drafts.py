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

# Pretty low burden, not bad if wanting to do a drop and re-load across full history.

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

SLATE_FILTER_ENABLED = True
# Match slates where slate_name contains any of these substrings (e.g. "2026" → LIKE '%2026%')
SLATE_NAME_CONTAINS = [
    "2026 Season",
]
FULL_RELOAD = False
# When True, ignore the max_draft_at watermark and re-pull all drafts for the
# selected slates (SLATE_FILTER_ENABLED / SLATE_NAME_CONTAINS still apply).
# Existing rows are skipped on insert via ON CONFLICT DO NOTHING, not updated.


# -------------------------
# Routing
# -------------------------

SAMPLE_JSON_PATH = SAMPLES_DIR / f"sample__{Path(__file__).stem}.json"

# -------------------------
# Helpers
# -------------------------

DEFAULT_MAX_DRAFT_AT = "2020-01-01T00:00:00Z"

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


def get_max_draft_at_from_db(conn):
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(payload->>'draft_at') FROM landing.ud_drafts")
            result = cur.fetchone()
            return result[0] if result and result[0] else DEFAULT_MAX_DRAFT_AT
    except Exception as e:
        print(f"⚠️ Fallback triggered — couldn't query landing.ud_drafts: {e}")
        return DEFAULT_MAX_DRAFT_AT


def get_headers(token):
    return {"Authorization": f"Bearer {token}", "User-Agent": "Mozilla/5.0"}


def collect_drafts(token, slates_to_run, conn=None, *, max_draft_at=None, record_limit=None):
    all_drafts = []
    inserted = 0
    drafts_collected = 0

    try:
        for slate in tqdm(slates_to_run, desc="Fetching drafts", unit="slate"):
            if record_limit is not None and drafts_collected >= record_limit:
                break

            page = 1
            while True:
                url = f"https://api.underdogfantasy.com/v2/user/slates/{slate['id']}/{slate['key']}?page={page}"
                try:
                    resp = requests.get(url, headers=get_headers(token), timeout=REQUEST_TIMEOUT)
                except requests.RequestException as e:
                    print(f"⚠️ Network error on slate {slate['slate_name']} page {page}: {e}")
                    break
                if resp.status_code == 401:
                    print(
                        f"🛑 Auth failed on slate {slate['slate_name']} (401 Unauthorized). Token likely expired."
                    )
                    return all_drafts, inserted, True
                if resp.status_code != 200:
                    print(
                        f"❌ Failed to get drafts for slate {slate['id']} (status: {resp.status_code})"
                    )
                    break

                page_drafts = resp.json().get("drafts", [])
                if not page_drafts:
                    break

                if max_draft_at is not None:
                    page_drafts = [
                        d for d in page_drafts if d.get("draft_at") and d["draft_at"] > max_draft_at
                    ]

                if record_limit is not None:
                    remaining = record_limit - drafts_collected
                    page_drafts = page_drafts[:remaining]

                if page_drafts:
                    if conn is not None:
                        inserted += insert_drafts(conn, page_drafts)
                    else:
                        all_drafts.extend(page_drafts)
                    drafts_collected += len(page_drafts)

                if record_limit is not None and drafts_collected >= record_limit:
                    break

                page += 1
                time.sleep(SLEEP_SECONDS)

    except KeyboardInterrupt:
        print("\n🛑 Interrupted by user — keeping data fetched so far.")
        return all_drafts, inserted, False

    return all_drafts, inserted, False


def insert_drafts(conn, drafts):
    if not drafts:
        return 0

    inserted = 0
    with conn.cursor() as cur:
        for draft in drafts:
            cur.execute(
                """
                INSERT INTO landing.ud_drafts (payload)
                VALUES (%s)
                ON CONFLICT ((payload->>'id')) DO NOTHING
                """,
                (Json(draft),),
            )
            inserted += cur.rowcount
    conn.commit()
    return inserted


def write_sample_json(drafts):
    SAMPLE_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SAMPLE_JSON_PATH.open("w") as f:
        json.dump(drafts, f, indent=2)
    print(f"📄 Wrote {len(drafts)} drafts to {SAMPLE_JSON_PATH}")


def main():
    auth = load_ud_auth()
    token = auth["auth_token"]
    slates_to_run = get_slates_to_run()

    if SLATE_FILTER_ENABLED:
        patterns = ", ".join(repr(p) for p in SLATE_NAME_CONTAINS)
        names = ", ".join(s["slate_name"] for s in slates_to_run)
        print(
            f"🎯 Slate filter enabled — name contains any of [{patterns}] ({len(slates_to_run)}): {names}"
        )

    if TEST_MODE:
        drafts, _inserted, unauthorized = collect_drafts(
            token, slates_to_run, record_limit=TEST_MODE_RECORD_LIMIT
        )
        if drafts:
            write_sample_json(drafts)
        if unauthorized:
            print(
                f"🛑 Stopping pull due to expired token. {len(drafts)} drafts saved to sample file."
            )
            return
        print(f"\n✅ Done. {len(drafts)} drafts written to sample file.")
        return

    conn = connect_to_db()
    if FULL_RELOAD:
        max_draft_at_in_db = None
        print(
            "🔁 FULL_RELOAD enabled — ignoring max_draft_at watermark and pulling all drafts for selected slates."
        )
    else:
        max_draft_at_in_db = get_max_draft_at_from_db(conn)
        print(f"🧭 Max draft_at in landing.ud_drafts: {max_draft_at_in_db}")

    _drafts, inserted, unauthorized = collect_drafts(
        token, slates_to_run, conn=conn, max_draft_at=max_draft_at_in_db
    )
    if unauthorized:
        print(f"🛑 Stopping pull due to expired token. {inserted} rows inserted before exit.")
        return

    print(f"\n✅ Done. {inserted} rows inserted.")


if __name__ == "__main__":
    main()
