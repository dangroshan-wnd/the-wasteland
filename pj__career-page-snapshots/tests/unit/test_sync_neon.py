from __future__ import annotations

import argparse

import pytest

from sync_neon import positive_integer, validate_database_urls

LOCAL_URL = "postgresql://user:password@127.0.0.1:5432/career_page_snapshots_dev"
NEON_URL = "postgresql://user:password@project.neon.tech:5432/career_page_snapshots"


def test_accepts_local_development_destination() -> None:
    validate_database_urls(LOCAL_URL, NEON_URL)


@pytest.mark.parametrize(
    ("local_url", "message"),
    [
        (
            "postgresql://user:password@database.example.com/career_page_snapshots_dev",
            "must point to localhost",
        ),
        (
            "postgresql://user:password@localhost/career_page_snapshots",
            "must end with '_dev'",
        ),
    ],
)
def test_rejects_unsafe_destination(local_url: str, message: str) -> None:
    with pytest.raises(RuntimeError, match=message):
        validate_database_urls(local_url, NEON_URL)


def test_rejects_identical_source_and_destination() -> None:
    with pytest.raises(RuntimeError, match="must be different"):
        validate_database_urls(LOCAL_URL, LOCAL_URL)


def test_positive_integer() -> None:
    assert positive_integer("25") == 25


def test_positive_integer_rejects_zero() -> None:
    with pytest.raises(argparse.ArgumentTypeError, match="at least 1"):
        positive_integer("0")
