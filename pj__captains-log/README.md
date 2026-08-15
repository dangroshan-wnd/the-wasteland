# Captain's Log

Wasteland-owned DDL for the Captain's Log journal tables. The Android app and
Render processor live in `captains-log`; this project is the local Postgres
schema and the empty publish to Neon.

Names follow [`naming.yml`](../naming.yml): `pj__captains-log` →
`captains_log.landing.<table>`.

| Environment | Database | Schema | Tables |
|---|---|---|---|
| Local | `captains_log_dev` | `landing` | `entries`, `processor_heartbeats` |
| Neon | `captains_log` | `landing` | same |

Create the local database once if it does not exist:

```sql
CREATE DATABASE captains_log_dev;
```

## Setup

```powershell
Copy-Item .env.example .env
```

Point `LOCAL_DATABASE_URL` at `captains_log_dev` and `NEON_DATABASE_URL` at the
captains-log Neon database. Keep `.env` untracked.

Needs `psycopg2` and `python-dotenv` (same stack as fantasy-football-ingestion).

## Apply locally (empty tables)

From this directory:

```powershell
python run_sql.py sql/ddl__captains_log__tables.sql
```

Confirm in local Postgres (connected to `captains_log_dev`):

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

That runs the same `CREATE SCHEMA` / `CREATE TABLE IF NOT EXISTS` against Neon.
It does not copy rows, drop tables, or truncate.
