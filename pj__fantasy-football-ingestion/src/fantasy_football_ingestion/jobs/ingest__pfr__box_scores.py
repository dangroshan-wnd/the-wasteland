import json
import random
import time
from pathlib import Path

from psycopg2.extras import Json
from tqdm import tqdm

from fantasy_football_ingestion.database import connect_to_db
from fantasy_football_ingestion.paths import SAMPLES_DIR
from fantasy_football_ingestion.scrapers.pro_football_reference import (
    PfrBrowserSession,
    scrape_boxscore_from_schedule_row,
)

# -------------------------
# Model Notes
# -------------------------

# One HTML scrape per game; reads schedules from landing. Skips already-ingested games.
# Optional SEASON_FILTER_ENABLED to limit which seasons are scraped.

# -------------------------
# Standard Toggles
# -------------------------

SLEEP_SECONDS = 13
SLEEP_JITTER = 4
TEST_MODE = False
TEST_MODE_RECORD_LIMIT = 2

# -------------------------
# Source Toggles
# -------------------------

SEASON_FILTER_ENABLED = True
# Inclusive start, exclusive end — same semantics as range(2020, 2025) → 2020–2024
SEASON_START = 2022
SEASON_END = 2025

# -------------------------
# Routing
# -------------------------

SAMPLE_JSON_PATH = SAMPLES_DIR / f"sample__{Path(__file__).stem}.json"

# -------------------------
# Defined Functions
# -------------------------


def get_games_from_db(conn):
    sql = """
        SELECT
            game_id,
            payload->>'week' AS week,
            payload->>'date' AS game_date,
            payload->>'season' AS season
        FROM landing.pfr_completed_season_schedules
    """
    params = []
    if SEASON_FILTER_ENABLED:
        sql += """
        WHERE (payload->>'season')::int >= %s
          AND (payload->>'season')::int < %s
        """
        params.extend([SEASON_START, SEASON_END])
    sql += """
        ORDER BY (payload->>'season')::int DESC, payload->>'week', game_id
    """
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return [
            {"game_id": r[0], "week": r[1], "game_date": r[2], "season": r[3]}
            for r in cur.fetchall()
            if r[0] is not None
        ]


def get_existing_game_ids(conn):
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT game_id FROM landing.pfr_box_scores")
            return {r[0] for r in cur.fetchall() if r[0] is not None}
    except Exception as e:
        print(f"⚠️ Couldn't query landing.pfr_box_scores, proceeding with full scrape: {e}")
        return set()


def insert_box_scores(conn, game_id, player_rows):
    if not player_rows:
        return 0

    inserted = 0
    with conn.cursor() as cur:
        for row in player_rows:
            cur.execute(
                """
                INSERT INTO landing.pfr_box_scores (payload, game_id)
                VALUES (%s, %s)
                ON CONFLICT (game_id, (payload->>'player')) DO NOTHING
                """,
                (Json(row), game_id),
            )
            inserted += cur.rowcount
    conn.commit()
    return inserted


def collect_box_scores(games, conn=None, *, record_limit=None):
    games_to_run = games[:record_limit] if record_limit else games
    all_rows = []
    inserted = 0

    try:
        with PfrBrowserSession() as browser:
            for game in tqdm(games_to_run, desc="Fetching box scores", unit="game"):
                try:
                    player_rows = scrape_boxscore_from_schedule_row(
                        game,
                        test_mode=TEST_MODE,
                        browser_session=browser,
                    )
                except Exception as e:
                    print(f"⚠️ Scrape failed for game {game['game_id']}: {e}")
                    player_rows = []

                if player_rows:
                    if conn is not None:
                        inserted += insert_box_scores(conn, game["game_id"], player_rows)
                    else:
                        all_rows.extend((row, game["game_id"]) for row in player_rows)

                if not TEST_MODE:
                    delay = random.uniform(
                        SLEEP_SECONDS - SLEEP_JITTER, SLEEP_SECONDS + SLEEP_JITTER
                    )
                    time.sleep(delay)
    except KeyboardInterrupt:
        print("\n🛑 Interrupted by user — keeping data fetched so far.")
        return all_rows, inserted

    return all_rows, inserted


def write_sample_json(rows):
    SAMPLE_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    payloads = [row for row, _game_id in rows]
    with SAMPLE_JSON_PATH.open("w") as f:
        json.dump(payloads, f, indent=2)
    print(f"📄 Wrote {len(payloads)} player rows to {SAMPLE_JSON_PATH}")


def main():
    conn = connect_to_db()
    if SEASON_FILTER_ENABLED:
        print(f"📅 Season filter: {SEASON_START}–{SEASON_END - 1}")
    else:
        print("📅 Season filter: disabled (all seasons in landing)")

    games = get_games_from_db(conn)
    print(f"📋 {len(games)} game(s) in landing.pfr_completed_season_schedules")

    existing_game_ids = get_existing_game_ids(conn)
    games = [g for g in games if g["game_id"] not in existing_game_ids]
    print(f"🔁 {len(games)} game(s) remaining after skipping already-ingested")

    if TEST_MODE:
        rows, _inserted = collect_box_scores(games, record_limit=TEST_MODE_RECORD_LIMIT)
        if rows:
            write_sample_json(rows)
        print(f"\n✅ Done. {len(rows)} player rows written to sample file.")
        return

    _rows, inserted = collect_box_scores(games, conn=conn)
    print(f"\n✅ Done. {inserted} rows inserted.")


if __name__ == "__main__":
    main()
