import json
from pathlib import Path

from psycopg2.extras import Json

from fantasy_football_ingestion.database import connect_to_db
from fantasy_football_ingestion.paths import SAMPLES_DIR
from fantasy_football_ingestion.scrapers.pro_football_reference import scrape_team_metadata

# -------------------------
# Model Notes
# -------------------------

# Single HTML scrape; upserts active NFL team metadata from PFR. Very fast. Shouldn't need to re-run.

# -------------------------
# Standard Toggles
# -------------------------

TEST_MODE = False
TEST_MODE_RECORD_LIMIT = 5

SAMPLE_JSON_PATH = SAMPLES_DIR / f"sample__{Path(__file__).stem}.json"

# -------------------------
# Defined Functions
# -------------------------


def fetch_active_teams():
    try:
        df = scrape_team_metadata()
        records = df.where(df.notna(), None).to_dict(orient="records")
        return [r for r in records if isinstance(r, dict)]
    except Exception as e:
        print(f"⚠️ Failed to scrape active teams: {e}")
        return None


def upsert_active_teams(conn, teams):
    if not teams:
        return 0

    count = 0
    with conn.cursor() as cur:
        for team in teams:
            cur.execute(
                """
                INSERT INTO landing.pfr_active_teams (payload)
                VALUES (%s)
                ON CONFLICT ((payload->>'pfr_abbr')) DO UPDATE SET
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
    teams = fetch_active_teams()
    if teams is None:
        print("❌ Failed to fetch active teams.")
        return

    print(f"📋 {len(teams)} active team(s) scraped")

    if TEST_MODE:
        teams = teams[:TEST_MODE_RECORD_LIMIT]
        write_sample_json(teams)
        print(f"\n✅ Done. {len(teams)} teams written to sample file.")
        return

    conn = connect_to_db()
    upserted = upsert_active_teams(conn, teams)
    print(f"\n✅ Done. {upserted} rows upserted.")


if __name__ == "__main__":
    main()
