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

# One API call per slate; upserts on (slate_id, player id). Auth required. Runs quite quickly (full re-load ~1 minute)

# -------------------------
# Standard Toggles
# -------------------------

SLEEP_SECONDS = 7
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


def fetch_players_for_slate(slate, token):
    url = f"https://stats.underdogfantasy.com/v1/slates/{slate['id']}/players"
    try:
        resp = requests.get(url, headers=get_headers(token), timeout=REQUEST_TIMEOUT)
    except requests.RequestException as e:
        print(f"⚠️ Network error for slate {slate['slate_name']}: {e}")
        return None
    if resp.status_code == 401:
        print(
            f"🛑 Auth failed on slate {slate['slate_name']} (401 Unauthorized). Token likely expired."
        )
        return "unauthorized"
    if resp.status_code != 200:
        print(f"❌ Error {resp.status_code} for slate {slate['slate_name']}")
        return None
    try:
        return [p for p in resp.json().get("players", []) if isinstance(p, dict)]
    except Exception as e:
        print(f"⚠️ Exception parsing players for slate {slate['slate_name']}: {e}")
        return None


def collect_players(token, slates_to_run, conn=None, *, record_limit=None):
    slates_subset = slates_to_run[:record_limit] if record_limit else slates_to_run
    all_players = []
    upserted = 0

    try:
        for slate in tqdm(slates_subset, desc="Fetching players", unit="slate"):
            players = fetch_players_for_slate(slate, token)
            if players == "unauthorized":
                return all_players, upserted, True
            if players is None:
                continue
            if players:
                pairs = [(p, slate["id"]) for p in players]
                if conn is not None:
                    upserted += upsert_players(conn, pairs)
                else:
                    all_players.extend(pairs)
            time.sleep(SLEEP_SECONDS)
    except KeyboardInterrupt:
        print("\n🛑 Interrupted by user — keeping data fetched so far.")
        return all_players, upserted, False

    return all_players, upserted, False


def upsert_players(conn, players):
    if not players:
        return 0

    count = 0
    with conn.cursor() as cur:
        for player, slate_id in players:
            cur.execute(
                """
                INSERT INTO landing.ud_players (payload, slate_id)
                VALUES (%s, %s)
                ON CONFLICT (slate_id, (payload->>'id')) DO UPDATE SET
                    payload = EXCLUDED.payload,
                    ingested_at = NOW()
                """,
                (Json(player), slate_id),
            )
            count += cur.rowcount
    conn.commit()
    return count


def write_sample_json(players):
    SAMPLE_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    payloads = [player for player, _slate_id in players]
    with SAMPLE_JSON_PATH.open("w") as f:
        json.dump(payloads, f, indent=2)
    print(f"📄 Wrote {len(payloads)} players to {SAMPLE_JSON_PATH}")


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
        players, _upserted, unauthorized = collect_players(
            token, slates_to_run, record_limit=TEST_MODE_RECORD_LIMIT
        )
        if players:
            write_sample_json(players)
        if unauthorized:
            print(
                f"🛑 Stopping pull due to expired token. {len(players)} players saved to sample file."
            )
            return
        print(f"\n✅ Done. {len(players)} players written to sample file.")
        return

    conn = connect_to_db()
    _players, upserted, unauthorized = collect_players(token, slates_to_run, conn=conn)
    if unauthorized:
        print(f"🛑 Stopping pull due to expired token. {upserted} rows upserted before exit.")
        return

    print(f"\n✅ Done. {upserted} rows upserted.")


if __name__ == "__main__":
    main()
