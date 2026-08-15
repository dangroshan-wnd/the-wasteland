# Captain's Log

Wasteland-owned DDL for the Captain's Log journal tables. The Android app and
Render processor live in `captains-log`; this project is the local Postgres
schema and the empty publish to Neon.

Database `captains_log` is listed in [`databases.yml`](../databases.yml).
Schema and table names are in `sql/ddl__captains_log__tables.sql`:
`landing.entries` and `landing.processor_heartbeats`. Same database name
locally and on Neon.

Create the database once if it does not exist:

```sql
CREATE DATABASE captains_log;
```

## Setup

```powershell
Copy-Item .env.example .env
```

Point `LOCAL_DATABASE_URL` and `NEON_DATABASE_URL` at the `captains_log`
database. Keep `.env` untracked.

Needs `psycopg2` and `python-dotenv` (same stack as fantasy-football-ingestion).

## Apply locally (empty tables)

From this directory:

```powershell
python run_sql.py sql/ddl__captains_log__tables.sql
```

Confirm:

```sql
SELECT COUNT(*) FROM landing.entries;
SELECT COUNT(*) FROM landing.processor_heartbeats;
```

Both should be `0`.

## Push empty schema to Neon

After the local tables exist and look right:

```powershell
python scripts/publish_schema_to_neon.py
```

That runs the same DDL against Neon. It does not copy rows, drop tables, or
truncate.
