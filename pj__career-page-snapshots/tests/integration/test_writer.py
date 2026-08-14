"""Postgres integration coverage for idempotent snapshot persistence."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
import pytest
from alembic.config import Config
from psycopg.errors import CheckViolation, NotNullViolation

from alembic import command
from career_page_snapshots.database import SnapshotRecord, persist_snapshot
from career_page_snapshots.models import (
    CollectionResult,
    NormalizedJob,
    PageMetadata,
    SourceMetadata,
)

pytestmark = pytest.mark.integration
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _test_database_url() -> str:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    if not urlsplit(database_url).path.lstrip("/").endswith("_test"):
        pytest.fail("refusing persistence test: database name must end with '_test'")
    return database_url


@pytest.fixture
def database_url(monkeypatch: pytest.MonkeyPatch) -> str:
    database_url = _test_database_url()
    config = Config(PROJECT_ROOT / "alembic.ini")
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    monkeypatch.setenv("DATABASE_URL", database_url)
    command.upgrade(config, "head")
    with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute("TRUNCATE landing.career_page_snapshots")
    return database_url


def _collection(*, title: str = "Software Engineer") -> CollectionResult:
    source_url = "https://boards-api.greenhouse.io/v1/boards/example/jobs"
    return CollectionResult(
        source=SourceMetadata(
            adapter="greenhouse",
            source_identifier="example",
            canonical_url=source_url,
            reported_job_count=1,
            pages=[PageMetadata(page_number=1, request_url=source_url, item_count=1)],
            metadata={"content_enabled": True, "attempt": 1},
        ),
        jobs=[
            NormalizedJob(
                external_job_id="job-1",
                title=title,
                location=["New York, NY", "Remote"],
                department=["Engineering"],
                url="https://jobs.example.com/job-1",
                description=None,
                raw_payload={"id": 1, "attributes": {"active": True}},
            )
        ],
    )


def _snapshot(*, title: str = "Software Engineer") -> SnapshotRecord:
    return SnapshotRecord.from_collection(
        company_name="Example",
        collection_key="flow-run-123:Example",
        captured_at=datetime(2026, 8, 12, 15, 0, tzinfo=UTC),
        collection=_collection(title=title),
    )


def test_insert_and_jsonb_round_trip(database_url: str) -> None:
    expected = _snapshot()

    result = persist_snapshot(database_url, expected)

    assert result.inserted is True
    assert result.snapshot == expected
    assert result.snapshot.payload.jobs[0].location == ("New York, NY", "Remote")
    assert result.snapshot.payload.jobs[0].raw_payload == {
        "id": 1,
        "attributes": {"active": True},
    }


def test_retry_returns_first_snapshot_without_updating_it(database_url: str) -> None:
    first = persist_snapshot(database_url, _snapshot())
    retry_candidate = _snapshot(title="Changed during retry")

    retry = persist_snapshot(database_url, retry_candidate)

    assert first.inserted is True
    assert retry.inserted is False
    assert retry.snapshot == first.snapshot
    assert retry.snapshot.snapshot_id != retry_candidate.snapshot_id
    assert retry.snapshot.payload.jobs[0].title == "Software Engineer"
    with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM landing.career_page_snapshots")
        assert cursor.fetchone() == (1,)


def test_database_rejects_negative_job_count(database_url: str) -> None:
    with pytest.raises(CheckViolation), psycopg.connect(database_url) as connection:
        connection.execute(
            """
            INSERT INTO landing.career_page_snapshots
                (snapshot_id, company_name, captured_at, source_url,
                 job_count, payload, collection_key)
            VALUES (gen_random_uuid(), %s, now(), %s, %s, %s::jsonb, %s)
            """,
            ("Example", "https://example.com", -1, "{}", "run"),
        )


def test_database_rejects_null_company_name(database_url: str) -> None:
    with pytest.raises(NotNullViolation), psycopg.connect(database_url) as connection:
        connection.execute(
            """
            INSERT INTO landing.career_page_snapshots
                (snapshot_id, company_name, captured_at, source_url,
                 job_count, payload, collection_key)
            VALUES (gen_random_uuid(), NULL, now(), %s, %s, %s::jsonb, %s)
            """,
            ("https://example.com", 0, "{}", "run"),
        )
