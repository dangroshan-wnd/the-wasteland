"""Lever Postings API adapter used by Palantir."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from typing import Any

import httpx
from pydantic import ValidationError

from career_page_snapshots.config import LeverCompany, LeverRegion
from career_page_snapshots.models import (
    CollectionResult,
    NormalizedJob,
    PageMetadata,
    SourceMetadata,
)
from career_page_snapshots.scrapers.base import IncompleteCollectionError, ParsingError
from career_page_snapshots.scrapers.http import HttpRetryPolicy, request_with_retry

API_ROOTS = {
    LeverRegion.GLOBAL: "https://api.lever.co/v0/postings",
    LeverRegion.EU: "https://api.eu.lever.co/v0/postings",
}
USER_AGENT = "career-page-snapshots/0.1"


def parse_lever_payload(payload: object) -> tuple[NormalizedJob, ...]:
    """Parse one Lever postings page without performing I/O."""
    if not isinstance(payload, list):
        raise ParsingError("Lever payload must be an array")

    jobs: list[NormalizedJob] = []
    for index, raw_job in enumerate(payload):
        if not isinstance(raw_job, Mapping):
            raise ParsingError(f"Lever job at index {index} must be an object")

        categories = raw_job.get("categories")
        if categories is None:
            categories = {}
        if not isinstance(categories, Mapping):
            raise ParsingError(f"Lever job at index {index} has invalid categories")

        all_locations = categories.get("allLocations")
        if all_locations is None:
            single_location = categories.get("location")
            locations = [single_location] if single_location else []
        elif isinstance(all_locations, list):
            single_location = categories.get("location")
            locations = all_locations or ([single_location] if single_location else [])
        else:
            raise ParsingError(f"Lever job at index {index} has invalid allLocations")

        team = categories.get("team")
        try:
            jobs.append(
                NormalizedJob(
                    external_job_id=raw_job.get("id", ""),
                    title=raw_job.get("text", ""),
                    location=locations,
                    department=[team] if team else [],
                    url=raw_job.get("hostedUrl", ""),
                    description=raw_job.get("descriptionPlain"),
                    raw_payload=dict(raw_job),
                )
            )
        except ValidationError as exc:
            raise ParsingError(f"invalid Lever job at index {index}: {exc}") from exc
    return tuple(jobs)


class LeverScraper:
    """Collect all pages from a public Lever job board."""

    def __init__(
        self,
        company: LeverCompany,
        *,
        page_size: int = 100,
        max_pages: int = 100,
        page_delay_seconds: float = 0.25,
        retry_policy: HttpRetryPolicy | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if page_size < 1 or page_size > 100:
            raise ValueError("Lever page_size must be between 1 and 100")
        if max_pages < 1:
            raise ValueError("Lever max_pages must be at least 1")
        if page_delay_seconds < 0:
            raise ValueError("Lever page_delay_seconds cannot be negative")
        self.company = company
        self.page_size = page_size
        self.max_pages = max_pages
        self.page_delay_seconds = page_delay_seconds
        self.retry_policy = retry_policy or HttpRetryPolicy()
        self.sleep = sleep

    @property
    def endpoint(self) -> str:
        return f"{API_ROOTS[self.company.region]}/{self.company.slug}"

    @property
    def canonical_url(self) -> str:
        return f"{self.endpoint}?mode=json"

    def collect(self, client: httpx.Client) -> CollectionResult:
        all_jobs: list[NormalizedJob] = []
        pages: list[PageMetadata] = []
        seen_page_ids: set[tuple[str, ...]] = set()

        for page_number in range(1, self.max_pages + 1):
            skip = len(all_jobs)
            response = request_with_retry(
                client,
                "GET",
                self.endpoint,
                policy=self.retry_policy,
                params={"mode": "json", "skip": skip, "limit": self.page_size},
                headers={"Accept": "application/json", "User-Agent": USER_AGENT},
            )
            try:
                payload: Any = response.json()
            except ValueError as exc:
                raise ParsingError("Lever returned invalid JSON") from exc

            page_jobs = parse_lever_payload(payload)
            page_ids = tuple(job.external_job_id for job in page_jobs)
            if page_ids and page_ids in seen_page_ids:
                raise IncompleteCollectionError("Lever returned a repeated page")
            seen_page_ids.add(page_ids)

            pages.append(
                PageMetadata(
                    page_number=page_number,
                    request_url=str(response.request.url),
                    item_count=len(page_jobs),
                    cursor=skip,
                )
            )
            all_jobs.extend(page_jobs)
            if len(page_jobs) < self.page_size:
                break
            self.sleep(self.page_delay_seconds)
        else:
            raise IncompleteCollectionError(
                f"Lever collection exceeded the {self.max_pages}-page safety bound"
            )

        source = SourceMetadata(
            adapter="lever",
            source_identifier=self.company.slug,
            canonical_url=self.canonical_url,
            pages=pages,
            metadata={
                "region": self.company.region.value,
                "page_size": self.page_size,
                "page_delay_seconds": self.page_delay_seconds,
            },
        )
        try:
            return CollectionResult(source=source, jobs=all_jobs)
        except ValidationError as exc:
            raise IncompleteCollectionError(f"invalid complete Lever collection: {exc}") from exc
