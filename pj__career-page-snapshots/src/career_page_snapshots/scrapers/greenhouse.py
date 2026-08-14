"""Greenhouse Job Board adapter used by Kalshi."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx
from pydantic import ValidationError

from career_page_snapshots.config import GreenhouseCompany
from career_page_snapshots.models import (
    CollectionResult,
    NormalizedJob,
    PageMetadata,
    SourceMetadata,
)
from career_page_snapshots.scrapers.base import IncompleteCollectionError, ParsingError
from career_page_snapshots.scrapers.http import HttpRetryPolicy, request_with_retry

API_ROOT = "https://boards-api.greenhouse.io/v1/boards"
USER_AGENT = "career-page-snapshots/0.1"


def parse_greenhouse_payload(payload: object) -> tuple[tuple[NormalizedJob, ...], int]:
    """Parse one complete Greenhouse board-list response without performing I/O."""
    if not isinstance(payload, Mapping):
        raise ParsingError("Greenhouse payload must be an object")

    raw_jobs = payload.get("jobs")
    meta = payload.get("meta")
    if not isinstance(raw_jobs, list) or not isinstance(meta, Mapping):
        raise ParsingError("Greenhouse payload requires jobs and meta objects")

    reported_count = meta.get("total")
    if not isinstance(reported_count, int) or isinstance(reported_count, bool):
        raise ParsingError("Greenhouse meta.total must be a nonnegative integer")
    if reported_count < 0:
        raise ParsingError("Greenhouse meta.total must be a nonnegative integer")

    jobs: list[NormalizedJob] = []
    for index, raw_job in enumerate(raw_jobs):
        if not isinstance(raw_job, Mapping):
            raise ParsingError(f"Greenhouse job at index {index} must be an object")

        location = raw_job.get("location")
        location_name = location.get("name") if isinstance(location, Mapping) else None
        departments = raw_job.get("departments", [])
        if departments is None:
            departments = []
        if not isinstance(departments, list):
            raise ParsingError(f"Greenhouse job at index {index} has invalid departments")

        department_names = [
            department.get("name")
            for department in departments
            if isinstance(department, Mapping) and department.get("name")
        ]

        try:
            jobs.append(
                NormalizedJob(
                    external_job_id=str(raw_job.get("id", "")),
                    title=raw_job.get("title", ""),
                    location=[location_name] if location_name else [],
                    department=department_names,
                    url=raw_job.get("absolute_url", ""),
                    description=raw_job.get("content"),
                    raw_payload=dict(raw_job),
                )
            )
        except ValidationError as exc:
            raise ParsingError(f"invalid Greenhouse job at index {index}: {exc}") from exc

    if len(jobs) != reported_count:
        raise IncompleteCollectionError(
            f"Greenhouse reported {reported_count} jobs but returned {len(jobs)}"
        )
    return tuple(jobs), reported_count


class GreenhouseScraper:
    """Collect a complete public Greenhouse job board."""

    def __init__(
        self,
        company: GreenhouseCompany,
        *,
        retry_policy: HttpRetryPolicy | None = None,
    ) -> None:
        self.company = company
        self.retry_policy = retry_policy or HttpRetryPolicy()

    @property
    def canonical_url(self) -> str:
        return f"{API_ROOT}/{self.company.slug}/jobs?content=true"

    def collect(self, client: httpx.Client) -> CollectionResult:
        response = request_with_retry(
            client,
            "GET",
            f"{API_ROOT}/{self.company.slug}/jobs",
            policy=self.retry_policy,
            params={"content": "true"},
            headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        )
        try:
            payload: Any = response.json()
        except ValueError as exc:
            raise ParsingError("Greenhouse returned invalid JSON") from exc

        jobs, reported_count = parse_greenhouse_payload(payload)
        source = SourceMetadata(
            adapter="greenhouse",
            source_identifier=self.company.slug,
            canonical_url=self.canonical_url,
            reported_job_count=reported_count,
            pages=[
                PageMetadata(
                    page_number=1,
                    request_url=str(response.request.url),
                    item_count=len(jobs),
                )
            ],
            metadata={"content": True},
        )
        return CollectionResult(source=source, jobs=jobs)
