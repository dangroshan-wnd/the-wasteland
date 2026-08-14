"""Incrementally copy production snapshots from Neon into local Postgres."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

import psycopg
from psycopg.conninfo import conninfo_to_dict
from pydantic import Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_BATCH_SIZE = 500
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}

SELECT_SNAPSHOTS = """
    SELECT
        snapshot_id,
        company_name,
        captured_at,
        source_url,
        job_count,
        payload::text,
        collection_key
    FROM landing.career_page_snapshots
    ORDER BY captured_at, snapshot_id
"""

INSERT_SNAPSHOTS = """
    INSERT INTO landing.career_page_snapshots (
        snapshot_id,
        company_name,
        captured_at,
        source_url,
        job_count,
        payload,
        collection_key
    )
    VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)
    ON CONFLICT (company_name, collection_key) DO NOTHING
"""


class SyncSettings(BaseSettings):
    """Database URLs loaded from the environment or the project's ignored .env file."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    local_database_url: SecretStr = Field(validation_alias="DATABASE_URL")
    neon_database_url: SecretStr = Field(validation_alias="NEON_DATABASE_URL")


def load_database_urls() -> tuple[str, str]:
    """Return the local destination and Neon source URLs without logging either value."""
    try:
        settings = SyncSettings()
    except ValidationError as exc:
        missing = {
            str(error["loc"][0])
            for error in exc.errors()
            if error["type"] == "missing" and error["loc"]
        }
        names = ", ".join(sorted(missing)) or "DATABASE_URL and NEON_DATABASE_URL"
        raise RuntimeError(f"Missing required configuration: {names}") from exc

    return (
        settings.local_database_url.get_secret_value(),
        settings.neon_database_url.get_secret_value(),
    )


def validate_database_urls(local_database_url: str, neon_database_url: str) -> None:
    """Refuse to write unless the destination is clearly the local development database."""
    if local_database_url == neon_database_url:
        raise RuntimeError("Neon and local database URLs must be different")

    try:
        local = conninfo_to_dict(local_database_url)
        conninfo_to_dict(neon_database_url)
    except psycopg.ProgrammingError as exc:
        raise RuntimeError("DATABASE_URL or NEON_DATABASE_URL is not a valid Postgres URL") from exc

    host = (local.get("host") or "").lower()
    database = local.get("dbname") or ""
    if host not in LOCAL_HOSTS:
        raise RuntimeError(
            "Refusing to sync: DATABASE_URL must point to localhost, 127.0.0.1, or ::1"
        )
    if not database.endswith("_dev"):
        raise RuntimeError("Refusing to sync: the local database name must end with '_dev'")


def run_command(command: list[str], *, env: dict[str, str] | None = None) -> None:
    """Run one setup command and convert missing executables into a useful error."""
    try:
        subprocess.run(command, cwd=PROJECT_ROOT, env=env, check=True)
    except FileNotFoundError as exc:
        raise RuntimeError(f"Required command is not installed or available: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"Setup command failed: {' '.join(command)}") from exc


def prepare_local_database(local_database_url: str, *, start_docker: bool) -> None:
    """Start local Postgres when requested and migrate its schema to the current revision."""
    if start_docker:
        print("Starting local Postgres...")
        run_command(["docker", "compose", "up", "-d", "postgres"])

    print("Applying local database migrations...")
    migration_env = os.environ.copy()
    migration_env["DATABASE_URL"] = local_database_url
    run_command(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        env=migration_env,
    )


def sync_snapshots(
    local_database_url: str,
    neon_database_url: str,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> tuple[int, int]:
    """Copy all Neon snapshots, skipping collection keys already present locally."""
    processed = 0
    inserted = 0

    with (
        psycopg.connect(neon_database_url) as neon_connection,
        psycopg.connect(local_database_url) as local_connection,
        neon_connection.cursor(name="neon_snapshot_sync") as source_cursor,
        local_connection.cursor() as destination_cursor,
    ):
        source_cursor.execute(SELECT_SNAPSHOTS)
        while rows := source_cursor.fetchmany(batch_size):
            destination_cursor.executemany(INSERT_SNAPSHOTS, rows)
            processed += len(rows)
            inserted += max(destination_cursor.rowcount, 0)

    return processed, inserted


def positive_integer(value: str) -> int:
    """Argparse converter for a positive batch size."""
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Incrementally copy Neon landing snapshots into local development Postgres."
    )
    parser.add_argument(
        "--batch-size",
        type=positive_integer,
        default=DEFAULT_BATCH_SIZE,
        help=f"rows copied per batch (default: {DEFAULT_BATCH_SIZE})",
    )
    parser.add_argument(
        "--skip-docker",
        action="store_true",
        help="do not run 'docker compose up -d postgres' before syncing",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        local_database_url, neon_database_url = load_database_urls()
        validate_database_urls(local_database_url, neon_database_url)
        prepare_local_database(local_database_url, start_docker=not args.skip_docker)
        print("Copying production snapshots from Neon into local Postgres...")
        processed, inserted = sync_snapshots(
            local_database_url,
            neon_database_url,
            batch_size=args.batch_size,
        )
    except (RuntimeError, psycopg.Error) as exc:
        print(f"Sync failed: {exc}", file=sys.stderr)
        return 1

    print(
        f"Sync complete: read {processed} Neon snapshots, inserted {inserted}, "
        f"already local {processed - inserted}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
