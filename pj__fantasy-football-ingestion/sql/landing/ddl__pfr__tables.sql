/* HOW TO RUN */
-- from powershell terminal, in project root, run:
-- `python run_sql.py sql/landing/ddl__pfr__tables.sql`

CREATE SCHEMA IF NOT EXISTS landing;

/* ACTIVE TEAMS */

CREATE TABLE IF NOT EXISTS landing.pfr_active_teams (
    payload JSONB NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_landing_pfr_active_teams_pfr_abbr
    ON landing.pfr_active_teams ((payload->>'pfr_abbr'));

/* COMPLETED SEASON SCHEDULES */

CREATE TABLE IF NOT EXISTS landing.pfr_completed_season_schedules (
    payload JSONB NOT NULL,
    game_id TEXT NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_landing_pfr_schedules_game_id
    ON landing.pfr_completed_season_schedules (game_id);

CREATE INDEX IF NOT EXISTS idx_landing_pfr_schedules_season
    ON landing.pfr_completed_season_schedules ((payload->>'season'));

/* BOX SCORES */

CREATE TABLE IF NOT EXISTS landing.pfr_box_scores (
    payload JSONB NOT NULL,
    game_id TEXT NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_landing_pfr_box_scores_game_player
    ON landing.pfr_box_scores (game_id, (payload->>'player'));

CREATE INDEX IF NOT EXISTS idx_landing_pfr_box_scores_game_id
    ON landing.pfr_box_scores (game_id);

/* PLAYERS */

CREATE TABLE IF NOT EXISTS landing.pfr_players (
    payload JSONB NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_landing_pfr_players_url
    ON landing.pfr_players ((payload->>'url'));

CREATE INDEX IF NOT EXISTS idx_landing_pfr_players_name
    ON landing.pfr_players ((payload->>'name'));
