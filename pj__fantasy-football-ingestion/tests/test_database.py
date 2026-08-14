from __future__ import annotations

import pytest

from fantasy_football_ingestion import database


def test_database_url_takes_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(database, "load_dotenv", lambda *_args, **_kwargs: None)
    monkeypatch.setenv("DATABASE_URL", "postgresql://example")
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    monkeypatch.setattr(
        database.psycopg2,
        "connect",
        lambda *args, **kwargs: calls.append((args, kwargs)) or object(),
    )

    database.connect_to_db()

    assert calls == [(("postgresql://example",), {})]


def test_named_postgres_settings_are_project_local(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(database, "load_dotenv", lambda *_args, **_kwargs: None)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    expected = {
        "PG_HOST": "localhost",
        "PG_PORT": "5432",
        "PG_NAME": "fantasy",
        "PG_USER": "postgres",
        "PG_PASS": "secret",
    }
    for name, value in expected.items():
        monkeypatch.setenv(name, value)
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        database.psycopg2,
        "connect",
        lambda **kwargs: captured.update(kwargs) or object(),
    )

    database.connect_to_db()

    assert captured == {
        "host": "localhost",
        "port": "5432",
        "dbname": "fantasy",
        "user": "postgres",
        "password": "secret",
    }


def test_missing_database_settings_fail_before_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(database, "load_dotenv", lambda *_args, **_kwargs: None)
    for name in ("DATABASE_URL", *database._PG_ENV_NAMES):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(RuntimeError, match="PG_HOST"):
        database.connect_to_db()
