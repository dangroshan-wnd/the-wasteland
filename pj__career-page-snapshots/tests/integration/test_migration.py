"""Destructive migration checks restricted to a dedicated disposable test database."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
import pytest
from alembic.config import Config

from alembic import command

pytestmark = pytest.mark.integration

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _test_database_url() -> str:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not configured")

    database_name = urlsplit(database_url).path.lstrip("/")
    if not database_name.endswith("_test"):
        pytest.fail("refusing destructive migration test: database name must end with '_test'")
    return database_url


def _alembic_config(database_url: str) -> Config:
    config = Config(PROJECT_ROOT / "alembic.ini")
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    os.environ["DATABASE_URL"] = database_url
    return config


def test_upgrade_and_downgrade_preserve_unrelated_landing_objects() -> None:
    database_url = _test_database_url()
    config = _alembic_config(database_url)

    command.downgrade(config, "base")
    with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute("CREATE SCHEMA IF NOT EXISTS landing")
        cursor.execute("DROP TABLE IF EXISTS landing.migration_test_sentinel")
        cursor.execute("CREATE TABLE landing.migration_test_sentinel (value integer NOT NULL)")

    try:
        command.upgrade(config, "head")
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'landing'
                  AND table_name = 'career_page_snapshots'
                ORDER BY ordinal_position
                """
            )
            columns = cursor.fetchall()
            assert columns == [
                ("snapshot_id", "uuid", "NO"),
                ("company_name", "text", "NO"),
                ("captured_at", "timestamp with time zone", "NO"),
                ("source_url", "text", "NO"),
                ("job_count", "integer", "NO"),
                ("payload", "jsonb", "NO"),
                ("collection_key", "text", "NO"),
            ]

            cursor.execute(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = 'landing'
                  AND tablename = 'career_page_snapshots'
                """
            )
            index_names = {row[0] for row in cursor.fetchall()}
            assert {
                "pk_career_page_snapshots",
                "uq_career_page_snapshots_company_collection",
                "ix_career_page_snapshots_company_captured_at",
                "ix_career_page_snapshots_captured_at",
            } <= index_names

            cursor.execute(
                """
                SELECT conname
                FROM pg_constraint
                WHERE conrelid = 'landing.career_page_snapshots'::regclass
                """
            )
            constraint_names = {row[0] for row in cursor.fetchall()}
            assert {
                "pk_career_page_snapshots",
                "uq_career_page_snapshots_company_collection",
                "ck_career_page_snapshots_job_count",
            } <= constraint_names

        command.downgrade(config, "base")
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT to_regclass('landing.career_page_snapshots')")
            assert cursor.fetchone() == (None,)
            cursor.execute("SELECT to_regclass('landing.migration_test_sentinel')")
            assert cursor.fetchone() == ("landing.migration_test_sentinel",)
    finally:
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute("DROP TABLE IF EXISTS landing.migration_test_sentinel")
