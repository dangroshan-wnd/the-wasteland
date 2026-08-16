"""Apply the empty captains-log DDL to Neon. Never copies or deletes rows."""

from __future__ import annotations

import os
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DDL_PATH = PROJECT_ROOT / "sql" / "ddl__captains_log__tables.sql"
TABLES = ("landing.entries", "landing.processor_heartbeats")


def _has_sql(stmt: str) -> bool:
    """True if the split chunk has a real statement (DDL comments may contain ';')."""
    for line in stmt.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("--"):
            return True
    return False


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env", override=True)
    neon_url = os.getenv("NEON_DATABASE_URL")
    if not neon_url:
        raise RuntimeError("NEON_DATABASE_URL is required")

    statements = [
        stmt.strip()
        for stmt in DDL_PATH.read_text().split(";")
        if _has_sql(stmt)
    ]
    conn = psycopg2.connect(neon_url)
    try:
        with conn.cursor() as cur:
            for stmt in statements:
                cur.execute(stmt)
            for table in TABLES:
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                count = cur.fetchone()[0]
                print(f"Neon {table}: {count:,} rows")
        conn.commit()
    finally:
        conn.close()

    print(f"Applied empty schema: {DDL_PATH.name}")


if __name__ == "__main__":
    main()
