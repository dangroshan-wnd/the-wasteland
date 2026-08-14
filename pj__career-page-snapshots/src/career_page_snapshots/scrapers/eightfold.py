"""Eightfold candidate-site adapter used by Netflix."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from typing import Any

import httpx
from pydantic import ValidationError

from career_page_snapshots.config import EightfoldCompany
from career_page_snapshots.models import (
    CollectionResult,
    NormalizedJob,
    PageMetadata,
    SourceMetadata,
)
from career_page_snapshots.scrapers.base import IncompleteCollectionError, ParsingError
from career_page_snapshots.scrapers.http import HttpRetryPolicy, request_with_retry

USER_AGENT = "career-page-snapshots/0.1"


class _UnstableInventoryError(IncompleteCollectionError):
    """The board changed while its ordered pages were being collected."""


def parse_eightfold_payload(payload: object) -> tuple[tuple[NormalizedJob, ...], int]:
    """Parse one Eightfold inventory page without performing I/O."""
    if not isinstance(payload, Mapping):
        raise ParsingError("Eightfold payload must be an object")

    raw_jobs = payload.get("positions")
    reported_count = payload.get("count")
    if not isinstance(raw_jobs, list):
        raise ParsingError("Eightfold payload requires a positions array")
    if (
        not isinstance(reported_count, int)
        or isinstance(reported_count, bool)
        or reported_count < 0
    ):
        raise ParsingError("Eightfold count must be a nonnegative integer")

    jobs: list[NormalizedJob] = []
    for index, raw_job in enumerate(raw_jobs):
        if not isinstance(raw_job, Mapping):
            raise ParsingError(f"Eightfold position at index {index} must be an object")

        raw_locations = raw_job.get("locations")
        if raw_locations is None:
            location = raw_job.get("location")
            locations = [location] if location else []
        elif isinstance(raw_locations, list):
            location = raw_job.get("location")
            locations = raw_locations or ([location] if location else [])
        else:
            raise ParsingError(f"Eightfold position at index {index} has invalid locations")

        department = raw_job.get("department")
        try:
            jobs.append(
                NormalizedJob(
                    external_job_id=str(raw_job.get("id", "")),
                    title=raw_job.get("name") or raw_job.get("posting_name") or "",
                    location=locations,
                    department=[department] if department else [],
                    url=raw_job.get("canonicalPositionUrl", ""),
                    description=raw_job.get("job_description"),
                    raw_payload=dict(raw_job),
                )
            )
        except ValidationError as exc:
            raise ParsingError(f"invalid Eightfold position at index {index}: {exc}") from exc
    return tuple(jobs), reported_count


def parse_eightfold_detail_description(payload: object) -> str | None:
    """Parse the optional description exposed by an Eightfold detail response."""
    if not isinstance(payload, Mapping):
        raise ParsingError("Eightfold detail payload must be an object")
    description = payload.get("job_description")
    if description is None:
        return None
    if not isinstance(description, str):
        raise ParsingError("Eightfold job_description must be text or null")
    return description.strip() or None


class EightfoldScraper:
    """Collect a complete Eightfold inventory without per-job detail requests."""

    def __init__(
        self,
        company: EightfoldCompany,
        *,
        page_size: int = 10,
        max_pages: int = 250,
        page_delay_seconds: float = 0.25,
        inventory_attempts: int = 2,
        inventory_retry_delay_seconds: float = 1.0,
        retry_policy: HttpRetryPolicy | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if page_size < 1 or page_size > 10:
            raise ValueError("Eightfold page_size must be between 1 and 10")
        if max_pages < 1:
            raise ValueError("Eightfold max_pages must be at least 1")
        if page_delay_seconds < 0:
            raise ValueError("Eightfold page_delay_seconds cannot be negative")
        if inventory_attempts < 1 or inventory_attempts > 3:
            raise ValueError("Eightfold inventory_attempts must be between 1 and 3")
        if inventory_retry_delay_seconds < 0:
            raise ValueError("Eightfold inventory_retry_delay_seconds cannot be negative")
        self.company = company
        self.page_size = page_size
        self.max_pages = max_pages
        self.page_delay_seconds = page_delay_seconds
        self.inventory_attempts = inventory_attempts
        self.inventory_retry_delay_seconds = inventory_retry_delay_seconds
        self.retry_policy = retry_policy or HttpRetryPolicy()
        self.sleep = sleep

    @property
    def endpoint(self) -> str:
        return f"https://{self.company.careers_host}/api/apply/v2/jobs"

    @property
    def canonical_url(self) -> str:
        return f"{self.endpoint}?domain={self.company.domain}"

    def collect(self, client: httpx.Client) -> CollectionResult:
        """Collect a stable inventory, restarting once if the live ordering changes."""
        for inventory_attempt in range(1, self.inventory_attempts + 1):
            try:
                return self._collect_once(client, inventory_attempt=inventory_attempt)
            except _UnstableInventoryError:
                if inventory_attempt == self.inventory_attempts:
                    raise
                self.sleep(self.inventory_retry_delay_seconds)
        raise AssertionError("inventory retry loop terminated without returning or raising")

    def _collect_once(self, client: httpx.Client, *, inventory_attempt: int) -> CollectionResult:
        all_jobs: list[NormalizedJob] = []
        pages: list[PageMetadata] = []
        reported_count: int | None = None
        seen_page_ids: set[tuple[str, ...]] = set()

        for page_number in range(1, self.max_pages + 1):
            start = len(all_jobs)
            response = request_with_retry(
                client,
                "GET",
                self.endpoint,
                policy=self.retry_policy,
                params={
                    "domain": self.company.domain,
                    "query": "",
                    "location": "",
                    "start": start,
                    "num": self.page_size,
                    "sort_by": "timestamp",
                },
                headers={"Accept": "application/json", "User-Agent": USER_AGENT},
            )
            try:
                payload: Any = response.json()
            except ValueError as exc:
                raise ParsingError("Eightfold returned invalid JSON") from exc

            page_jobs, page_reported_count = parse_eightfold_payload(payload)
            if reported_count is None:
                reported_count = page_reported_count
            elif page_reported_count != reported_count:
                raise _UnstableInventoryError("Eightfold reported count changed during pagination")

            page_ids = tuple(job.external_job_id for job in page_jobs)
            if page_ids and page_ids in seen_page_ids:
                raise _UnstableInventoryError("Eightfold returned a repeated page")
            seen_page_ids.add(page_ids)

            pages.append(
                PageMetadata(
                    page_number=page_number,
                    request_url=str(response.request.url),
                    item_count=len(page_jobs),
                    cursor=start,
                )
            )
            all_jobs.extend(page_jobs)

            if len(all_jobs) == reported_count:
                break
            if len(all_jobs) > reported_count:
                raise _UnstableInventoryError(
                    f"Eightfold returned {len(all_jobs)} jobs after reporting {reported_count}"
                )
            if not page_jobs:
                raise _UnstableInventoryError(
                    f"Eightfold pagination ended after {len(all_jobs)} of {reported_count} jobs"
                )
            self.sleep(self.page_delay_seconds)
        else:
            raise IncompleteCollectionError(
                f"Eightfold collection exceeded the {self.max_pages}-page safety bound"
            )

        assert reported_count is not None
        job_ids = [job.external_job_id for job in all_jobs]
        if len(job_ids) != len(set(job_ids)):
            raise _UnstableInventoryError(
                "Eightfold returned duplicate job IDs while the board was changing"
            )
        source = SourceMetadata(
            adapter="eightfold",
            source_identifier=f"{self.company.careers_host}:{self.company.domain}",
            canonical_url=self.canonical_url,
            reported_job_count=reported_count,
            pages=pages,
            metadata={
                "page_size": self.page_size,
                "page_delay_seconds": self.page_delay_seconds,
                "detail_enrichment": False,
                "inventory_attempt": inventory_attempt,
            },
        )
        try:
            return CollectionResult(source=source, jobs=all_jobs)
        except ValidationError as exc:
            raise IncompleteCollectionError(
                f"invalid complete Eightfold collection: {exc}"
            ) from exc
