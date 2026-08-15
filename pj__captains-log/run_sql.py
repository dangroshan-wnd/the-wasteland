"""Apply a SQL file to local Postgres. Splits on ';' — no function bodies."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent
WASTELAND_ROOT = PROJECT_ROOT.parent
if str(WASTELAND_ROOT) not in sys.path:
    sys.path.insert(0, str(WASTELAND_ROOT))

from naming import names_for  # noqa: E402

_PG_ENV_NAMES = ("PG_HOST", "PG_PORT", "PG_NAME", "PG_USER", "PG_PASS")
NAMES = names_for(PROJECT_ROOT.name)


def connect_to_db():
    load_dotenv(PROJECT_ROOT / ".env")
    database_url = os.getenv("LOCAL_DATABASE_URL") or os.getenv("DATABASE_URL")
    if database_url:
        return psycopg2.connect(database_url)

    missing = [name for name in _PG_ENV_NAMES if not os.getenv(name)]
    if missing:
        names = ", ".join(missing)
        raise RuntimeError(
            "Missing local database configuration: set LOCAL_DATABASE_URL "
            f"or DATABASE_URL, or {names}. Expected database "
            f"{NAMES.local_database}."
        )

    return psycopg2.connect(
        host=os.environ["PG_HOST"],
        port=os.environ["PG_PORT"],
        dbname=os.environ.get("PG_NAME", NAMES.local_database),
        user=os.environ["PG_USER"],
        password=os.environ["PG_PASS"],
    )


def run_sql_file(path: Path) -> None:
    statements = [stmt.strip() for stmt in path.read_text().split(";") if stmt.strip()]
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

    print(f"Applying to {NAMES.qualified} (local db {NAMES.local_database})")
    run_sql_file(path)
    print(f"Done: {path}")


if __name__ == "__main__":
    main()
