-- HOW TO RUN
-- From the repository root:
--   python pj__captains-log/run_sql.py pj__captains-log/sql/ddl__captains_log__tables.sql
--
-- Or, from pj__captains-log/:
--   python run_sql.py sql/ddl__captains_log__tables.sql
--
-- Do not run this .sql file directly with Python.
--
-- Then, publish the empty schema only (no rows):
--   python scripts/publish_schema_to_neon.py
--
-- Pull Neon landing rows onto local Postgres (replaces local rows):
--   python scripts/sync_neon_to_postgres.py
--
-- Names (same locally and on Neon):
--   database  captains_log
--   schema    landing
--   tables    landing.entries
--             landing.processor_heartbeats
--
-- Create the database once if it does not exist (from postgres):
--   CREATE DATABASE captains_log;
-- Then connect to captains_log and run this file.

CREATE SCHEMA IF NOT EXISTS landing;

-- ENTRIES - one row per journal video (PK = client ULID)

CREATE TABLE IF NOT EXISTS landing.entries (
    id VARCHAR(64) PRIMARY KEY,
    drive_video_id VARCHAR(128),
    drive_sidecar_id VARCHAR(128),
    drive_ready_id VARCHAR(128),
    storage_provider VARCHAR(32),
    storage_video_key VARCHAR(256),
    storage_sidecar_key VARCHAR(256),
    storage_ready_key VARCHAR(256),
    source VARCHAR(32) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    journal_date DATE NOT NULL,
    duration_ms INTEGER,
    processing_status VARCHAR(32) NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ,
    lease_owner VARCHAR(128),
    lease_expires_at TIMESTAMPTZ,
    last_error TEXT,
    transcript TEXT,
    title TEXT,
    summary TEXT,
    topics_json JSON,
    decisions_json JSON,
    action_items_json JSON,
    llm_provider VARCHAR(32),
    llm_model VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    processed_at TIMESTAMPTZ,
    disposition_score INTEGER,
    energy_score INTEGER,
    physical_score INTEGER,
    sharpness_score INTEGER,
    aggregate_score INTEGER,
    spoken_score_spans_json JSON,
    emphasis_spans_json JSON,
    emphases_json JSON,
    CONSTRAINT uq_entries_drive_video_id UNIQUE (drive_video_id),
    CONSTRAINT uq_entries_drive_sidecar_id UNIQUE (drive_sidecar_id),
    CONSTRAINT uq_entries_drive_ready_id UNIQUE (drive_ready_id),
    CONSTRAINT uq_entries_storage_video_key UNIQUE (storage_video_key),
    CONSTRAINT uq_entries_storage_sidecar_key UNIQUE (storage_sidecar_key),
    CONSTRAINT uq_entries_storage_ready_key UNIQUE (storage_ready_key),
    CONSTRAINT ck_entries_disposition_score CHECK (disposition_score BETWEEN 1 AND 5),
    CONSTRAINT ck_entries_energy_score CHECK (energy_score BETWEEN 1 AND 5),
    CONSTRAINT ck_entries_physical_score CHECK (physical_score BETWEEN 1 AND 5),
    CONSTRAINT ck_entries_sharpness_score CHECK (sharpness_score BETWEEN 1 AND 5),
    CONSTRAINT ck_entries_aggregate_score CHECK (aggregate_score BETWEEN 1 AND 5)
);

-- Existing beta databases: add spoken metadata, then remove legacy Mood values and columns.

ALTER TABLE landing.entries
    ADD COLUMN IF NOT EXISTS storage_provider VARCHAR(32),
    ADD COLUMN IF NOT EXISTS storage_video_key VARCHAR(256),
    ADD COLUMN IF NOT EXISTS storage_sidecar_key VARCHAR(256),
    ADD COLUMN IF NOT EXISTS storage_ready_key VARCHAR(256),
    ADD COLUMN IF NOT EXISTS disposition_score INTEGER
        CONSTRAINT ck_entries_disposition_score CHECK (disposition_score BETWEEN 1 AND 5),
    ADD COLUMN IF NOT EXISTS energy_score INTEGER
        CONSTRAINT ck_entries_energy_score CHECK (energy_score BETWEEN 1 AND 5),
    ADD COLUMN IF NOT EXISTS physical_score INTEGER
        CONSTRAINT ck_entries_physical_score CHECK (physical_score BETWEEN 1 AND 5),
    ADD COLUMN IF NOT EXISTS sharpness_score INTEGER
        CONSTRAINT ck_entries_sharpness_score CHECK (sharpness_score BETWEEN 1 AND 5),
    ADD COLUMN IF NOT EXISTS aggregate_score INTEGER
        CONSTRAINT ck_entries_aggregate_score CHECK (aggregate_score BETWEEN 1 AND 5),
    ADD COLUMN IF NOT EXISTS spoken_score_spans_json JSON,
    ADD COLUMN IF NOT EXISTS emphasis_spans_json JSON,
    ADD COLUMN IF NOT EXISTS emphases_json JSON,
    DROP COLUMN IF EXISTS mood,
    DROP COLUMN IF EXISTS mood_span;

CREATE UNIQUE INDEX IF NOT EXISTS uq_entries_storage_video_key
    ON landing.entries (storage_video_key);

CREATE UNIQUE INDEX IF NOT EXISTS uq_entries_storage_sidecar_key
    ON landing.entries (storage_sidecar_key);

CREATE UNIQUE INDEX IF NOT EXISTS uq_entries_storage_ready_key
    ON landing.entries (storage_ready_key);

CREATE INDEX IF NOT EXISTS ix_entries_journal_date
    ON landing.entries (journal_date);

CREATE INDEX IF NOT EXISTS ix_entries_processing_status
    ON landing.entries (processing_status);

-- PROCESSOR HEARTBEATS - poller liveness

CREATE TABLE IF NOT EXISTS landing.processor_heartbeats (
    name VARCHAR(64) PRIMARY KEY,
    last_tick_at TIMESTAMPTZ NOT NULL,
    last_success_at TIMESTAMPTZ,
    last_error TEXT
);
