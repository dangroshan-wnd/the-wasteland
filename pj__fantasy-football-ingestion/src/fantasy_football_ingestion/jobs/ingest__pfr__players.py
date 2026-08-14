import json
from pathlib import Path

from psycopg2.extras import Json

from fantasy_football_ingestion.database import connect_to_db
from fantasy_football_ingestion.paths import SAMPLES_DIR
from fantasy_football_ingestion.scrapers.pro_football_reference import scrape_players

# -------------------------
# Model Notes
# -------------------------

# One HTML scrape per letter index + per eligible player detail page.
# Career end-year cutoff is enforced by scrape_players. Slow for full alphabet.
# Upserts each player to landing as soon as its detail page is scraped.
# Skips player URLs already present in landing.pfr_players.

# -------------------------
# Standard Toggles
# -------------------------

TEST_MODE = False
TEST_MODE_RECORD_LIMIT = 5

# -------------------------
# Source Toggles
# -------------------------

# Letters to scrape (e.g. "F" for a smoke test, full alphabet for production "ABCDEFGHIJKLMNOPQRSTUVWXYZ")
LETTERS = "PQRSTUVWXYZ"
BATCH_SIZE = 5

# -------------------------
# Routing
# -------------------------

SAMPLE_JSON_PATH = SAMPLES_DIR / f"sample__{Path(__file__).stem}.json"

# -------------------------
# Defined Functions
# -------------------------


def get_existing_player_urls(conn):
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT payload->>'url' FROM landing.pfr_players")
            return {r[0] for r in cur.fetchall() if r[0] is not None}
    except Exception as e:
        print(f"Couldn't query landing.pfr_players, proceeding with full scrape: {e}")
        return set()


def upsert_player(conn, player):
    if not player or not player.get("url"):
        return 0

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO landing.pfr_players (payload)
            VALUES (%s)
            ON CONFLICT ((payload->>'url')) DO NOTHING
            """,
            (Json(player),),
        )
        inserted = cur.rowcount
    conn.commit()
    return inserted


def write_sample_json(players):
    SAMPLE_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SAMPLE_JSON_PATH.open("w") as f:
        json.dump(players, f, indent=2)
    print(f"Wrote {len(players)} players to {SAMPLE_JSON_PATH}")


def main():
    print(f"Letters to scrape: {LETTERS}")

    conn = connect_to_db()
    existing_urls = get_existing_player_urls(conn)
    print(f"{len(existing_urls)} player URL(s) already in landing.pfr_players")

    inserted = 0
    scraped = []

    def on_player(player):
        nonlocal inserted
        if TEST_MODE:
            scraped.append(player)
            return
        inserted += upsert_player(conn, player)

    try:
        players = scrape_players(
            letters=LETTERS,
            batch_size=BATCH_SIZE,
            skip_urls=existing_urls,
            on_player=on_player,
            max_players=TEST_MODE_RECORD_LIMIT if TEST_MODE else None,
        )
    except KeyboardInterrupt:
        print("\nInterrupted — keeping players written to landing so far.")
        players = scraped
    except Exception as e:
        print(f"Failed to scrape players: {e}")
        print(f"Rows inserted before failure: {inserted}")
        return

    if TEST_MODE:
        players = (players or scraped)[:TEST_MODE_RECORD_LIMIT]
        write_sample_json(players)
        print(f"\nDone. {len(players)} players written to sample file.")
        return

    print(f"\nDone. {inserted} rows inserted ({len(players)} new player(s) scraped).")


if __name__ == "__main__":
    main()
