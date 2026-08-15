/* HOW TO RUN */
-- from powershell, in pj__captains-log/:
--   python run_sql.py sql/ddl__captains_log__tables.sql
--
-- then, empty schema only (no rows):
--   python scripts/publish_schema_to_neon.py
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

/* ENTRIES — one row per journal video (PK = client ULID) */

CREATE TABLE IF NOT EXISTS landing.entries (
    id VARCHAR(64) PRIMARY KEY,
    drive_video_id VARCHAR(128),
    drive_sidecar_id VARCHAR(128),
    drive_ready_id VARCHAR(128),
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
    mood INTEGER,
    mood_span VARCHAR(128),
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
    CONSTRAINT uq_entries_drive_video_id UNIQUE (drive_video_id),
    CONSTRAINT uq_entries_drive_sidecar_id UNIQUE (drive_sidecar_id),
    CONSTRAINT uq_entries_drive_ready_id UNIQUE (drive_ready_id)
);

CREATE INDEX IF NOT EXISTS ix_entries_journal_date
    ON landing.entries (journal_date);

CREATE INDEX IF NOT EXISTS ix_entries_processing_status
    ON landing.entries (processing_status);

/* PROCESSOR HEARTBEATS — poller liveness */

CREATE TABLE IF NOT EXISTS landing.processor_heartbeats (
    name VARCHAR(64) PRIMARY KEY,
    last_tick_at TIMESTAMPTZ NOT NULL,
    last_success_at TIMESTAMPTZ,
    last_error TEXT
);
