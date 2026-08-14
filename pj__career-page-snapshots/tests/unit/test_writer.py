"""Unit coverage for snapshot row construction."""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from career_page_snapshots.database import SnapshotRecord
from career_page_snapshots.models import (
    CollectionResult,
    NormalizedJob,
    PageMetadata,
    SourceMetadata,
)


def _collection() -> CollectionResult:
    source_url = "https://boards-api.greenhouse.io/v1/boards/example/jobs"
    return CollectionResult(
        source=SourceMetadata(
            adapter="greenhouse",
            source_identifier="example",
            canonical_url=source_url,
            reported_job_count=1,
            pages=[PageMetadata(page_number=1, request_url=source_url, item_count=1)],
            metadata={"content_enabled": True},
        ),
        jobs=[
            NormalizedJob(
                external_job_id="job-1",
                title="Software Engineer",
                location=["Remote"],
                department=["Engineering"],
                url="https://jobs.example.com/job-1",
                raw_payload={"id": "job-1", "listed": True},
            )
        ],
    )


def test_snapshot_record_constructs_versioned_payload_and_row_fields() -> None:
    captured_at = datetime(2026, 8, 12, 14, 30, tzinfo=UTC)

    snapshot = SnapshotRecord.from_collection(
        company_name="Example",
        collection_key="flow-run-id:Example",
        captured_at=captured_at,
        collection=_collection(),
    )

    assert snapshot.company_name == "Example"
    assert snapshot.captured_at == captured_at
    assert snapshot.collection_key == "flow-run-id:Example"
    assert snapshot.source_url == "https://boards-api.greenhouse.io/v1/boards/example/jobs"
    assert snapshot.job_count == 1
    assert snapshot.payload.schema_version == 1
    assert snapshot.payload.job_count == 1
    assert snapshot.payload.jobs[0].raw_payload == {"id": "job-1", "listed": True}


def test_snapshot_record_rejects_non_utc_capture_timestamp() -> None:
    with pytest.raises(ValidationError, match="captured_at must be in UTC"):
        SnapshotRecord.from_collection(
            company_name="Example",
            collection_key="run-1",
            captured_at=datetime(2026, 8, 12, 10, tzinfo=timezone(timedelta(hours=-4))),
            collection=_collection(),
        )


@pytest.mark.parametrize("field", ["company_name", "collection_key"])
def test_snapshot_record_rejects_blank_idempotency_fields(field: str) -> None:
    values = {
        "company_name": "Example",
        "collection_key": "run-1",
        "captured_at": datetime(2026, 8, 12, tzinfo=UTC),
        "collection": _collection(),
    }
    values[field] = " "

    with pytest.raises(ValidationError, match="at least 1 character"):
        SnapshotRecord.from_collection(**values)
