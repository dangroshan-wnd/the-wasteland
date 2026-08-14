"""Idempotent persistence for complete company snapshots."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Self
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from career_page_snapshots.models import CollectionResult, NonEmptyString, SnapshotEnvelope

_TABLE = sql.Identifier("landing", "career_page_snapshots")
_COLUMNS = sql.SQL(
    "snapshot_id, company_name, captured_at, source_url, job_count, payload, collection_key"
)


class SnapshotRecord(BaseModel):
    """A validated row ready to be written to or read from Postgres."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: UUID = Field(default_factory=uuid4)
    company_name: NonEmptyString
    captured_at: AwareDatetime
    source_url: NonEmptyString
    job_count: int = Field(ge=0)
    payload: SnapshotEnvelope
    collection_key: NonEmptyString

    @field_validator("captured_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("captured_at must be in UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def match_payload_count(self) -> Self:
        if self.job_count != self.payload.job_count:
            raise ValueError("job_count must match the snapshot payload")
        return self

    @classmethod
    def from_collection(
        cls,
        *,
        company_name: str,
        collection_key: str,
        captured_at: datetime,
        collection: CollectionResult,
    ) -> Self:
        """Construct a storage row from one validated complete collection."""
        payload = SnapshotEnvelope.from_collection(collection)
        return cls(
            company_name=company_name,
            captured_at=captured_at,
            source_url=collection.source.canonical_url,
            job_count=collection.job_count,
            payload=payload,
            collection_key=collection_key,
        )


class WriteResult(BaseModel):
    """The durable row and whether this call inserted it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot: SnapshotRecord
    inserted: bool


def _snapshot_from_database_row(row: dict[str, Any]) -> SnapshotRecord:
    """Normalize Postgres session-local timestamps before contract validation."""
    captured_at = row.get("captured_at")
    if isinstance(captured_at, datetime) and captured_at.tzinfo is not None:
        row = {**row, "captured_at": captured_at.astimezone(UTC)}
    return SnapshotRecord.model_validate(row)


def write_snapshot(connection: psycopg.Connection[Any], snapshot: SnapshotRecord) -> WriteResult:
    """Insert a snapshot once, returning the first row on an idempotency conflict.

    Transaction ownership remains with the caller. The conflict lookup is a
    separate statement so PostgreSQL can observe a concurrently committed row
    under the default READ COMMITTED isolation level.
    """
    insert_query = sql.SQL(
        """
        INSERT INTO {} ({})
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (company_name, collection_key) DO NOTHING
        RETURNING {}
        """
    ).format(_TABLE, _COLUMNS, _COLUMNS)
    values = (
        snapshot.snapshot_id,
        snapshot.company_name,
        snapshot.captured_at,
        snapshot.source_url,
        snapshot.job_count,
        Jsonb(snapshot.payload.model_dump(mode="json")),
        snapshot.collection_key,
    )

    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(insert_query, values)
        row = cursor.fetchone()
        if row is not None:
            return WriteResult(snapshot=_snapshot_from_database_row(row), inserted=True)

        cursor.execute(
            sql.SQL("SELECT {} FROM {} WHERE company_name = %s AND collection_key = %s").format(
                _COLUMNS, _TABLE
            ),
            (snapshot.company_name, snapshot.collection_key),
        )
        existing = cursor.fetchone()

    if existing is None:
        raise RuntimeError("snapshot conflict occurred but the existing row was not found")
    return WriteResult(snapshot=_snapshot_from_database_row(existing), inserted=False)


def persist_snapshot(database_url: str, snapshot: SnapshotRecord) -> WriteResult:
    """Persist and commit one snapshot using a database URL."""
    with psycopg.connect(database_url) as connection:
        return write_snapshot(connection, snapshot)
