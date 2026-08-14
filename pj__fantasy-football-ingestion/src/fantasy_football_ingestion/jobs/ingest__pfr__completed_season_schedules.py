import json
import random
import time
from pathlib import Path

from psycopg2.extras import Json

from fantasy_football_ingestion.database import connect_to_db
from fantasy_football_ingestion.paths import SAMPLES_DIR
from fantasy_football_ingestion.scrapers.pro_football_reference import scrape_season_schedule

# -------------------------
# Model Notes
# -------------------------

# One HTML scrape per season; full replace per season on each run.
# Pretty fast, ~2 minutes for 5 seasons.

# -------------------------
# Standard Toggles
# -------------------------

TEST_MODE = False
TEST_MODE_RECORD_LIMIT = 1  # seasons, not games

SLEEP_SECONDS = 13
SLEEP_JITTER = 4

# -------------------------
# Source Toggles
# -------------------------

# Inclusive start, exclusive end — same semantics as range(2020, 2025) → 2020–2024
SEASON_START = 2020
SEASON_END = 2026

SAMPLE_JSON_PATH = SAMPLES_DIR / f"sample__{Path(__file__).stem}.json"

# -------------------------
# Defined Functions
# -------------------------


def get_seasons_to_run():
    return list(range(SEASON_START, SEASON_END))


def derive_game_id(date_str, home_abbr):
    if not date_str or not home_abbr:
        return None
    return f"{date_str}0{home_abbr}"


def scrape_season_games(season):
    try:
        df = scrape_season_schedule(season)
        if df.empty:
            return []
        records = df.where(df.notna(), None).to_dict(orient="records")
        games = []
        for record in records:
            if not isinstance(record, dict):
                continue
            game_id = derive_game_id(record.get("date"), record.get("home_abbr"))
            if not game_id:
                print(f"⚠️ Skipping game with missing game_id: {record}")
                continue
            record["game_id"] = game_id
            games.append((record, game_id))
        return games
    except Exception as e:
        print(f"⚠️ Failed to scrape schedule for season {season}: {e}")
        return None


def replace_season_schedules(conn, season, games):
    with conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM landing.pfr_completed_season_schedules
            WHERE payload->>'season' = %s
            """,
            (str(season),),
        )
        deleted = cur.rowcount
        for payload, game_id in games:
            cur.execute(
                """
                INSERT INTO landing.pfr_completed_season_schedules (payload, game_id)
                VALUES (%s, %s)
                """,
                (Json(payload), game_id),
            )
    conn.commit()
    return deleted, len(games)


def write_sample_json(games):
    SAMPLE_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    payloads = [payload for payload, _game_id in games]
    with SAMPLE_JSON_PATH.open("w") as f:
        json.dump(payloads, f, indent=2)
    print(f"📄 Wrote {len(payloads)} games to {SAMPLE_JSON_PATH}")


def sleep_between_seasons(season_index, total_seasons):
    if season_index >= total_seasons - 1:
        return
    delay = random.uniform(SLEEP_SECONDS - SLEEP_JITTER, SLEEP_SECONDS + SLEEP_JITTER)
    print(f"⏸️ Sleeping {delay:.1f}s before next season...")
    time.sleep(delay)


def main():
    seasons = get_seasons_to_run()
    if TEST_MODE:
        seasons = seasons[:TEST_MODE_RECORD_LIMIT]

    print(f"📅 Seasons to scrape: {seasons} (range {SEASON_START}–{SEASON_END - 1})")

    if TEST_MODE:
        all_games = []
        for i, season in enumerate(seasons):
            games = scrape_season_games(season)
            if games:
                all_games.extend(games)
            sleep_between_seasons(i, len(seasons))
        if all_games:
            write_sample_json(all_games)
        print(f"\n✅ Done. {len(all_games)} games written to sample file.")
        return

    conn = connect_to_db()
    total_inserted = 0
    for i, season in enumerate(seasons):
        print(f"\n🔄 Scraping schedule for {season}...")
        games = scrape_season_games(season)
        if games is None:
            print(f"❌ Skipping season {season} due to scrape failure.")
            sleep_between_seasons(i, len(seasons))
            continue
        deleted, inserted = replace_season_schedules(conn, season, games)
        total_inserted += inserted
        print(f"📊 Season {season}: replaced {deleted} row(s), inserted {inserted} game(s)")
        sleep_between_seasons(i, len(seasons))

    print(f"\n✅ Done. {total_inserted} games inserted across {len(seasons)} season(s).")


if __name__ == "__main__":
    main()
