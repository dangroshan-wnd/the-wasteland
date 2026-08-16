"""Apply a SQL file to local Postgres. Splits on ';' — no function bodies."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_PG_NAME = "captains_log"
_PG_ENV_NAMES = ("PG_HOST", "PG_PORT", "PG_USER", "PG_PASS")


def connect_to_db():
    load_dotenv(PROJECT_ROOT / ".env", override=True)
    missing = [name for name in _PG_ENV_NAMES if not os.getenv(name)]
    if not missing:
        return psycopg2.connect(
            host=os.environ["PG_HOST"],
            port=os.environ["PG_PORT"],
            dbname=os.getenv("PG_NAME") or DEFAULT_PG_NAME,
            user=os.environ["PG_USER"],
            password=os.environ["PG_PASS"],
        )

    database_url = os.getenv("LOCAL_DATABASE_URL") or os.getenv("DATABASE_URL")
    if database_url:
        return psycopg2.connect(database_url)

    names = ", ".join(missing)
    raise RuntimeError(
        "Missing local database configuration in pj__captains-log/.env: "
        f"set {names}, or LOCAL_DATABASE_URL"
    )


def _contains_sql(statement: str) -> bool:
    return any(
        line.strip() and not line.lstrip().startswith("--")
        for line in statement.splitlines()
    )


def run_sql_file(path: Path) -> None:
    statements = [
        statement.strip()
        for statement in path.read_text(encoding="utf-8").split(";")
        if _contains_sql(statement)
    ]
    conn = connect_to_db()
    try:
        with conn.cursor() as cur:
            for stmt in statements:
                cur.execute(stmt)
        conn.commit()
    finally:
        conn.close()


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python run_sql.py <path-to-sql-file>")

    path = Path(sys.argv[1])
    if not path.is_file():
        raise SystemExit(f"File not found: {path}")

    run_sql_file(path)
    print(f"Done: {path}")


if __name__ == "__main__":
    main()
