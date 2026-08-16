"""Replace local landing rows with a snapshot from Neon. Never writes to Neon."""

from __future__ import annotations

import os
import sys
from io import StringIO
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DDL_PATH = PROJECT_ROOT / "sql" / "ddl__captains_log__tables.sql"
TABLES = ("landing.entries", "landing.processor_heartbeats")

sys.path.insert(0, str(PROJECT_ROOT))
from run_sql import connect_to_db  # noqa: E402


def _has_sql(stmt: str) -> bool:
    return any(
        line.strip() and not line.strip().startswith("--")
        for line in stmt.splitlines()
    )


def _require_direct_neon_url() -> str:
    url = (os.getenv("NEON_DATABASE_URL") or "").strip()
    if not url:
        raise RuntimeError("NEON_DATABASE_URL is required in pj__captains-log/.env")
    if "-pooler" in url:
        raise RuntimeError(
            "NEON_DATABASE_URL is the -pooler host. Use the Neon direct host."
        )
    return url


def _ensure_local_schema(local) -> None:
    statements = [
        stmt.strip() for stmt in DDL_PATH.read_text(encoding="utf-8").split(";") if _has_sql(stmt)
    ]
    with local.cursor() as cur:
        for stmt in statements:
            cur.execute(stmt)


def _copy_table(neon_cur, local_cur, table: str) -> int:
    buf = StringIO()
    neon_cur.copy_expert(f"COPY {table} TO STDOUT", buf)
    buf.seek(0)
    local_cur.copy_expert(f"COPY {table} FROM STDIN", buf)
    local_cur.execute(f"SELECT COUNT(*) FROM {table}")
    return int(local_cur.fetchone()[0])


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env", override=True)
    neon_url = _require_direct_neon_url()
    local = connect_to_db()
    try:
        neon = psycopg2.connect(neon_url)
        try:
            _ensure_local_schema(local)
            with neon.cursor() as neon_cur, local.cursor() as local_cur:
                local_cur.execute(
                    "TRUNCATE landing.entries, landing.processor_heartbeats"
                )
                counts: list[tuple[str, int]] = []
                for table in TABLES:
                    counts.append((table, _copy_table(neon_cur, local_cur, table)))
            local.commit()
        except Exception:
            local.rollback()
            raise
        finally:
            neon.close()
    finally:
        local.close()

    for table, count in counts:
        print(f"Local {table}: {count:,} rows (from Neon)")
    print("Replaced local landing rows with the Neon snapshot.")


if __name__ == "__main__":
    main()
