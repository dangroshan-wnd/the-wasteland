from datetime import datetime

import pytest
from pydantic import ValidationError

from career_page_snapshots.models import (
    CollectionResult,
    NormalizedJob,
    PageMetadata,
    SnapshotEnvelope,
    SourceMetadata,
)


def make_job(job_id: str = "job-1") -> NormalizedJob:
    return NormalizedJob(
        external_job_id=job_id,
        title="Software Engineer",
        location=["New York, NY", "new york, ny", "Remote"],
        department=["Engineering"],
        url=f"https://jobs.example.com/{job_id}",
        description="  Build reliable systems.  ",
        raw_payload={"id": job_id, "listed": True},
    )


def make_source(reported_job_count: int | None = 1) -> SourceMetadata:
    return SourceMetadata(
        adapter="greenhouse",
        source_identifier="example",
        canonical_url="https://boards-api.greenhouse.io/v1/boards/example/jobs",
        reported_job_count=reported_job_count,
        pages=[
            PageMetadata(
                page_number=1,
                request_url="https://boards-api.greenhouse.io/v1/boards/example/jobs",
                item_count=reported_job_count or 0,
            )
        ],
        metadata={"content_enabled": True},
    )


def test_normalized_job_preserves_collection_fields_and_serializes_to_json() -> None:
    job = make_job()

    assert job.location == ("New York, NY", "Remote")
    assert job.department == ("Engineering",)
    assert job.description == "Build reliable systems."
    assert job.model_dump(mode="json") == {
        "external_job_id": "job-1",
        "title": "Software Engineer",
        "location": ["New York, NY", "Remote"],
        "department": ["Engineering"],
        "url": "https://jobs.example.com/job-1",
        "description": "Build reliable systems.",
        "raw_payload": {"id": "job-1", "listed": True},
    }


def test_normalized_job_allows_missing_optional_fields() -> None:
    job = NormalizedJob(
        external_job_id="123",
        title="Analyst",
        url="https://jobs.example.com/123",
        raw_payload={"id": 123},
    )

    assert job.location == ()
    assert job.department == ()
    assert job.description is None


def test_normalized_job_converts_blank_description_to_none() -> None:
    job = NormalizedJob(
        external_job_id="123",
        title="Analyst",
        url="https://jobs.example.com/123",
        description="  ",
        raw_payload={"id": 123},
    )

    assert job.description is None


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"external_job_id": " "}, "at least 1 character"),
        ({"title": ""}, "at least 1 character"),
        ({"location": "New York"}, "must be a collection"),
        ({"url": "javascript:alert(1)"}, "URL scheme"),
        ({"url": "https://user:password@jobs.example.com/1"}, "credentials"),
        ({"raw_payload": {"observed_at": datetime.now()}}, "valid JSON value"),
    ],
)
def test_normalized_job_rejects_contract_violations(
    override: dict[str, object], message: str
) -> None:
    values: dict[str, object] = {
        "external_job_id": "job-1",
        "title": "Engineer",
        "url": "https://jobs.example.com/job-1",
        "raw_payload": {"id": "job-1"},
    }
    values.update(override)

    with pytest.raises(ValidationError, match=message):
        NormalizedJob.model_validate(values)


def test_collection_rejects_duplicate_external_job_ids() -> None:
    with pytest.raises(ValidationError, match="duplicate external job IDs"):
        CollectionResult(source=make_source(reported_job_count=2), jobs=[make_job(), make_job()])


def test_collection_rejects_reported_count_mismatch() -> None:
    with pytest.raises(ValidationError, match="source reported 2 jobs"):
        CollectionResult(source=make_source(reported_job_count=2), jobs=[make_job()])


def test_empty_collection_is_valid_when_source_reports_zero() -> None:
    collection = CollectionResult(source=make_source(reported_job_count=0), jobs=[])

    assert collection.job_count == 0


def test_source_metadata_requires_sequential_pages() -> None:
    with pytest.raises(ValidationError, match="page numbers must be sequential"):
        SourceMetadata(
            adapter="lever",
            source_identifier="example",
            canonical_url="https://api.lever.co/v0/postings/example",
            pages=[
                PageMetadata(
                    page_number=2,
                    request_url="https://api.lever.co/v0/postings/example?skip=20",
                    item_count=20,
                )
            ],
        )


def test_snapshot_envelope_is_versioned_and_matches_collection_count() -> None:
    collection = CollectionResult(source=make_source(), jobs=[make_job()])

    envelope = SnapshotEnvelope.from_collection(collection)

    assert envelope.schema_version == 1
    assert envelope.job_count == 1
    assert envelope.model_dump(mode="json")["jobs"][0]["external_job_id"] == "job-1"


def test_snapshot_envelope_rejects_job_count_mismatch() -> None:
    with pytest.raises(ValidationError, match="envelope contains 1 jobs"):
        SnapshotEnvelope(source=make_source(), job_count=0, jobs=[make_job()])
