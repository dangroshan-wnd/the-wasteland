/* HOW TO RUN */
-- from powershell terminal, in project root, run:
--`python run_sql.py sql/landing/ddl__ud__tables.sql`

CREATE SCHEMA IF NOT EXISTS landing;

/* DRAFTS */

CREATE TABLE IF NOT EXISTS landing.ud_drafts (
    payload JSONB NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_landing_ud_drafts_payload_id
    ON landing.ud_drafts ((payload->>'id'));

CREATE INDEX IF NOT EXISTS idx_landing_ud_drafts_draft_at
    ON landing.ud_drafts ((payload->>'draft_at'));


/* DRAFT ENTRIES */

CREATE TABLE IF NOT EXISTS landing.ud_draft_entries (
    payload JSONB NOT NULL,
    draft_id TEXT NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE landing.ud_draft_entries
    ADD COLUMN IF NOT EXISTS draft_id TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_landing_ud_draft_entries_payload_id
    ON landing.ud_draft_entries ((payload->>'id'));

CREATE INDEX IF NOT EXISTS idx_landing_ud_draft_entries_draft_id
    ON landing.ud_draft_entries (draft_id);

/* APPEARANCES */

CREATE TABLE IF NOT EXISTS landing.ud_appearances (
    payload JSONB NOT NULL,
    slate_id TEXT NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE landing.ud_appearances
    ADD COLUMN IF NOT EXISTS slate_id TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_landing_ud_appearances_payload_id
    ON landing.ud_appearances ((payload->>'id'));

CREATE INDEX IF NOT EXISTS idx_landing_ud_appearances_slate_id
    ON landing.ud_appearances (slate_id);

/* PLAYERS */

CREATE TABLE IF NOT EXISTS landing.ud_players (
    payload JSONB NOT NULL,
    slate_id TEXT NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE landing.ud_players
    ADD COLUMN IF NOT EXISTS slate_id TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_landing_ud_players_slate_player_id
    ON landing.ud_players (slate_id, (payload->>'id'));

CREATE INDEX IF NOT EXISTS idx_landing_ud_players_slate_id
    ON landing.ud_players (slate_id);

/* DRAFT ENTRY PICKS */

CREATE TABLE IF NOT EXISTS landing.ud_draft_entry_picks (
    payload JSONB NOT NULL,
    draft_id TEXT NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE landing.ud_draft_entry_picks
    ADD COLUMN IF NOT EXISTS draft_id TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_landing_ud_draft_entry_picks_payload_id
    ON landing.ud_draft_entry_picks ((payload->>'id'));

CREATE INDEX IF NOT EXISTS idx_landing_ud_draft_entry_picks_draft_id
    ON landing.ud_draft_entry_picks (draft_id);

/* TEAMS */

CREATE TABLE IF NOT EXISTS landing.ud_teams (
    payload JSONB NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_landing_ud_teams_payload_id
    ON landing.ud_teams ((payload->>'id'));

CREATE INDEX IF NOT EXISTS idx_landing_ud_teams_sport_id
    ON landing.ud_teams ((payload->>'sport_id'));


/* SLATES */

CREATE TABLE IF NOT EXISTS landing.ud_slates (
    payload JSONB NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_landing_ud_slates_payload_id
    ON landing.ud_slates ((payload->>'id'));

CREATE INDEX IF NOT EXISTS idx_landing_ud_slates_sport_id
    ON landing.ud_slates ((payload->>'sport_id'));

CREATE INDEX IF NOT EXISTS idx_landing_ud_slates_start_at
    ON landing.ud_slates ((payload->>'start_at'));


/* USERS */

CREATE TABLE IF NOT EXISTS landing.ud_users (
    payload JSONB NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_landing_ud_users_payload_id
    ON landing.ud_users ((payload->>'id'));
