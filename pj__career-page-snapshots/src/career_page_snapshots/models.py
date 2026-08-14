"""Source-neutral models for complete career-page collections."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    JsonValue,
    NonNegativeInt,
    PositiveInt,
    StringConstraints,
    TypeAdapter,
    field_validator,
    model_validator,
)

NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
AdapterName = Literal["greenhouse", "lever", "eightfold", "google"]

_HTTP_URL_ADAPTER = TypeAdapter(HttpUrl)


def _validate_http_url(value: str) -> str:
    normalized = value.strip()
    parsed = _HTTP_URL_ADAPTER.validate_python(normalized)
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URL credentials are not allowed")
    return normalized


class NormalizedJob(BaseModel):
    """A source job represented by the stable V1 normalized contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    external_job_id: NonEmptyString
    title: NonEmptyString
    location: tuple[NonEmptyString, ...] = ()
    department: tuple[NonEmptyString, ...] = ()
    url: NonEmptyString
    description: str | None = None
    raw_payload: JsonValue

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        return _validate_http_url(value)

    @field_validator("location", "department", mode="before")
    @classmethod
    def require_collection(cls, value: object) -> object:
        if isinstance(value, str):
            raise ValueError("must be a collection of strings, not one flattened string")
        return value

    @field_validator("location", "department")
    @classmethod
    def deduplicate_values(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            normalized = value.casefold()
            if normalized not in seen:
                seen.add(normalized)
                result.append(value)
        return tuple(result)

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class PageMetadata(BaseModel):
    """Bounded debugging metadata for one successfully retrieved source page."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    page_number: PositiveInt
    request_url: NonEmptyString
    item_count: NonNegativeInt
    cursor: JsonValue | None = None

    @field_validator("request_url")
    @classmethod
    def validate_request_url(cls, value: str) -> str:
        return _validate_http_url(value)


class SourceMetadata(BaseModel):
    """Source identity and retrieval facts retained with every snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    adapter: AdapterName
    source_identifier: NonEmptyString
    canonical_url: NonEmptyString
    reported_job_count: NonNegativeInt | None = None
    pages: tuple[PageMetadata, ...] = Field(min_length=1)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("canonical_url")
    @classmethod
    def validate_canonical_url(cls, value: str) -> str:
        return _validate_http_url(value)

    @model_validator(mode="after")
    def require_sequential_pages(self) -> Self:
        actual = tuple(page.page_number for page in self.pages)
        expected = tuple(range(1, len(self.pages) + 1))
        if actual != expected:
            raise ValueError(f"page numbers must be sequential from 1; received {actual!r}")
        return self


class CollectionResult(BaseModel):
    """One complete, successfully parsed company inventory."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: SourceMetadata
    jobs: tuple[NormalizedJob, ...]

    @property
    def job_count(self) -> int:
        return len(self.jobs)

    @model_validator(mode="after")
    def verify_completeness(self) -> Self:
        job_ids = [job.external_job_id for job in self.jobs]
        if len(job_ids) != len(set(job_ids)):
            raise ValueError("a complete collection cannot contain duplicate external job IDs")

        reported_count = self.source.reported_job_count
        if reported_count is not None and reported_count != len(self.jobs):
            raise ValueError(
                f"source reported {reported_count} jobs but collection contains {len(self.jobs)}"
            )
        return self


class SnapshotEnvelope(BaseModel):
    """Versioned JSONB payload stored for one company snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    source: SourceMetadata
    job_count: NonNegativeInt
    jobs: tuple[NormalizedJob, ...]

    @model_validator(mode="after")
    def verify_job_count(self) -> Self:
        if self.job_count != len(self.jobs):
            raise ValueError(
                f"job_count is {self.job_count} but envelope contains {len(self.jobs)} jobs"
            )
        return self

    @classmethod
    def from_collection(cls, collection: CollectionResult) -> SnapshotEnvelope:
        """Create the persisted envelope for a validated complete collection."""
        return cls(
            source=collection.source,
            job_count=collection.job_count,
            jobs=collection.jobs,
        )
