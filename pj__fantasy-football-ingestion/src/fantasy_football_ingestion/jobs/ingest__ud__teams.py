import json
from pathlib import Path

import requests
from psycopg2.extras import Json

from fantasy_football_ingestion.database import connect_to_db
from fantasy_football_ingestion.paths import SAMPLES_DIR
from fantasy_football_ingestion.underdog import teams_api_config

# -------------------------
# Model Notes
# -------------------------

# Single API call; response includes all sports. Filter via SPORT_ID_FILTER (default NFL).

# -------------------------
# Standard Toggles
# -------------------------

REQUEST_TIMEOUT = 30
TEST_MODE = False
TEST_MODE_RECORD_LIMIT = 5

# -------------------------
# Source Toggles
# -------------------------

# Keep only teams whose sport_id is in this list; empty list = no filter (all ~14k teams)
SPORT_ID_FILTER = [
    "NFL",
]

# -------------------------
# Routing
# -------------------------

SAMPLE_JSON_PATH = SAMPLES_DIR / f"sample__{Path(__file__).stem}.json"
TEAMS_URL = "https://stats.underdogfantasy.com/v1/teams"

# -------------------------
# Defined Functions
# -------------------------


def fetch_teams():
    try:
        resp = requests.get(
            TEAMS_URL,
            params=teams_api_config,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as e:
        print(f"⚠️ Network error fetching teams: {e}")
        return None
    if resp.status_code != 200:
        print(f"❌ Error {resp.status_code} fetching teams")
        return None
    try:
        teams = resp.json().get("teams", [])
        return [t for t in teams if isinstance(t, dict)]
    except Exception as e:
        print(f"⚠️ Exception parsing teams response: {e}")
        return None


def filter_teams(teams):
    if not SPORT_ID_FILTER:
        return teams
    allowed = set(SPORT_ID_FILTER)
    return [t for t in teams if t.get("sport_id") in allowed]


def upsert_teams(conn, teams):
    if not teams:
        return 0

    count = 0
    with conn.cursor() as cur:
        for team in teams:
            cur.execute(
                """
                INSERT INTO landing.ud_teams (payload)
                VALUES (%s)
                ON CONFLICT ((payload->>'id')) DO UPDATE SET
                    payload = EXCLUDED.payload,
                    ingested_at = NOW()
                """,
                (Json(team),),
            )
            count += cur.rowcount
    conn.commit()
    return count


def write_sample_json(teams):
    SAMPLE_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SAMPLE_JSON_PATH.open("w") as f:
        json.dump(teams, f, indent=2)
    print(f"📄 Wrote {len(teams)} teams to {SAMPLE_JSON_PATH}")


def main():
    if SPORT_ID_FILTER:
        print(f"🏈 Sport filter: {', '.join(SPORT_ID_FILTER)}")

    teams = fetch_teams()
    if teams is None:
        print("❌ Failed to fetch teams.")
        return

    teams = filter_teams(teams)
    print(f"📋 {len(teams)} team(s) after filter")

    if TEST_MODE:
        teams = teams[:TEST_MODE_RECORD_LIMIT]
        write_sample_json(teams)
        print(f"\n✅ Done. {len(teams)} teams written to sample file.")
        return

    conn = connect_to_db()
    upserted = upsert_teams(conn, teams)
    print(f"\n✅ Done. {upserted} rows upserted.")


if __name__ == "__main__":
    main()
