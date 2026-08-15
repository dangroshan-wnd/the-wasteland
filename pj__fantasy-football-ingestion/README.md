# Fantasy Football Ingestion

The Wasteland-owned loader for fantasy-football landing data. It contains the active Underdog and
Pro Football Reference ingestion jobs, their ordered protocols, sanitized samples, landing-table
DDL, and the explicit local/Neon transfer utilities that used to live in `fantasy-football`.

This project owns ingestion only. dbt models and source contracts live in
[`the-citadel`](https://github.com/dangroshan-wnd/the-citadel); the agent, Android application, and
retained analytical Python live in `fantasy-football`.

## Setup

Use Python 3.12 and run commands from this directory:

```powershell
uv sync --locked --dev
Copy-Item .env.example .env
```

Fill in the local Postgres settings required by the ingestion jobs. The publish/sync utilities also
use `LOCAL_DATABASE_URL` and `NEON_DATABASE_URL`. Keep the real `.env` untracked.

Authenticated Underdog jobs read `UD_AUTH_PATH`, which defaults to `secrets/ud_auth.json`. That
directory is ignored. Never commit authentication JSON.

## Run ingestion

The protocol commands execute real API/scraping work and write landing tables. Inspect each child
job's toggles before running one.

```powershell
uv run fantasy-ingest-annual
uv run fantasy-ingest-weekly-inseason
uv run fantasy-ingest-weekly-offseason
```

Run one job directly as a module when a full protocol is unnecessary:

```powershell
uv run python -m fantasy_football_ingestion.jobs.ingest__ud__slates
uv run python -m fantasy_football_ingestion.jobs.ingest__pfr__inprogress_season_schedules
uv run python -m fantasy_football_ingestion.jobs.ingest__pfr__box_scores
```

`samples/` contains the sanitized JSON fixtures retained from the source repository. A job in
`TEST_MODE` may refresh its corresponding sample without connecting to Postgres. The legacy dbt
seed fallback is intentionally absent; disabled seed CSVs remain in `fantasy-football` until that
repository's reduction step.

Landing DDL is under `sql/landing/`. Relation names remain unchanged so Citadel's sources continue
to resolve.

## Publish and sync utilities

These commands replace or truncate destination tables and therefore require deliberate use:

```powershell
uv run python scripts/publish_table_to_neon.py
uv run python scripts/publish_draft_picks_to_neon.py
uv run python scripts/sync_agent_logs_from_neon_to_postgres.py
```

The approved table list remains explicit in `publish_table_to_neon.py`.

## Validate without production writes

```powershell
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

These checks import every job and protocol, verify project-local paths/configuration, and do not
run production ingestion.
