"""Unit tests for non-destructive readiness checks."""

from __future__ import annotations

from pathlib import Path

import pytest

import career_page_snapshots.readiness as readiness
from career_page_snapshots.config import RuntimeSettings


class FakeCursor:
    def __init__(self, row: tuple[object, ...]) -> None:
        self.row = row
        self.query: str | None = None

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, query: str) -> None:
        self.query = query

    def fetchone(self) -> tuple[object, ...]:
        return self.row


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor

    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def cursor(self) -> FakeCursor:
        return self._cursor


def _settings(companies_file: Path) -> RuntimeSettings:
    return RuntimeSettings(
        DATABASE_URL="postgresql://user:password@localhost/database",
        COMPANIES_FILE=companies_file,
    )


def test_readiness_checks_configuration_and_database_without_writes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    companies_file = tmp_path / "companies.yml"
    companies_file.write_text(
        "companies:\n  - name: Example\n    scraper: greenhouse\n    slug: example\n",
        encoding="utf-8",
    )
    cursor = FakeCursor(
        ("career_page_snapshots_dev", "landing.career_page_snapshots", "20260812_01")
    )
    monkeypatch.setattr(
        readiness.psycopg,
        "connect",
        lambda _url: FakeConnection(cursor),
    )

    results = readiness.check_readiness(_settings(companies_file))

    assert all(result.passed for result in results)
    assert "Example" in results[0].detail
    assert "career_page_snapshots_dev" in results[1].detail
    assert "20260812_01" in results[2].detail
    assert cursor.query is not None
    assert "INSERT" not in cursor.query.upper()
    assert "UPDATE" not in cursor.query.upper()
    assert "DELETE" not in cursor.query.upper()


def test_readiness_fails_when_snapshot_table_is_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    companies_file = tmp_path / "companies.yml"
    companies_file.write_text(
        "companies:\n  - name: Example\n    scraper: greenhouse\n    slug: example\n",
        encoding="utf-8",
    )
    cursor = FakeCursor(("career_page_snapshots_dev", None, None))
    monkeypatch.setattr(
        readiness.psycopg,
        "connect",
        lambda _url: FakeConnection(cursor),
    )

    results = readiness.check_readiness(_settings(companies_file))

    assert results[-1].passed is False
    assert "run Alembic migrations" in results[-1].detail
