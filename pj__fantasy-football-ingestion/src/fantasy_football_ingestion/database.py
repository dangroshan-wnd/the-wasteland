"""Project-local Postgres connection configuration."""

from __future__ import annotations

import os

import psycopg2
from dotenv import load_dotenv

from fantasy_football_ingestion.paths import PROJECT_ROOT

_PG_ENV_NAMES = ("PG_HOST", "PG_PORT", "PG_NAME", "PG_USER", "PG_PASS")


def connect_to_db():
    """Connect to the landing database using this project's environment file."""
    load_dotenv(PROJECT_ROOT / ".env")
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return psycopg2.connect(database_url)

    missing = [name for name in _PG_ENV_NAMES if not os.getenv(name)]
    if missing:
        names = ", ".join(missing)
        raise RuntimeError(f"Missing database configuration: {names}")

    return psycopg2.connect(
        host=os.environ["PG_HOST"],
        port=os.environ["PG_PORT"],
        dbname=os.environ["PG_NAME"],
        user=os.environ["PG_USER"],
        password=os.environ["PG_PASS"],
    )
