"""Server-rendered Google Careers adapter."""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup, Tag
from pydantic import ValidationError

from career_page_snapshots.config import GoogleCompany
from career_page_snapshots.models import (
    CollectionResult,
    NormalizedJob,
    PageMetadata,
    SourceMetadata,
)
from career_page_snapshots.scrapers.base import IncompleteCollectionError, ParsingError
from career_page_snapshots.scrapers.http import HttpRetryPolicy, request_with_retry

BASE_URL = "https://www.google.com/about/careers/applications/"
RESULTS_URL = f"{BASE_URL}jobs/results"
USER_AGENT = "career-page-snapshots/0.1"
_RANGE_PATTERN = re.compile(
    r"Showing\s+([\d,]+)\s+to\s+([\d,]+)\s+of\s+([\d,]+)\s+rows",
    re.IGNORECASE,
)
_JOB_PATH_PATTERN = re.compile(r"(?:^|/)jobs/results/(\d+)(?:-|$)")


class _UnexpectedGooglePageError(ParsingError):
    """A successful response lacked the expected careers results document."""


@dataclass(frozen=True, slots=True)
class ParsedGooglePage:
    jobs: tuple[NormalizedJob, ...]
    range_start: int
    range_end: int
    reported_count: int
    next_url: str | None


def _canonical_job_url(href: str) -> tuple[str, str]:
    absolute = urljoin(BASE_URL, href)
    parsed = urlsplit(absolute)
    match = _JOB_PATH_PATTERN.search(parsed.path)
    if parsed.scheme != "https" or parsed.netloc != "www.google.com" or match is None:
        raise ParsingError(f"invalid Google job detail URL: {href!r}")
    canonical = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    return match.group(1), canonical


def _parse_google_card(card: Tag, index: int) -> NormalizedJob:
    title_node = card.select_one("h3.QJPWVe")
    detail_link = card.select_one('a[href][aria-label^="Learn more about"]')
    if title_node is None or detail_link is None:
        raise ParsingError(f"Google job card at index {index} lacks a title or detail link")

    href = detail_link.get("href")
    if not isinstance(href, str):
        raise ParsingError(f"Google job card at index {index} has an invalid detail link")
    external_job_id, canonical_url = _canonical_job_url(href)

    title = title_node.get_text(" ", strip=True)
    location_nodes = card.select(".wVoYLb .pwO9Dc .r0wTof")
    locations = [node.get_text(" ", strip=True).lstrip("; ") for node in location_nodes]
    company_node = card.select_one(".wVoYLb .RP7SMd span")
    company_name = company_node.get_text(" ", strip=True) if company_node else None
    qualification_nodes = card.select(".Xsxa1e li")
    qualifications = [node.get_text(" ", strip=True) for node in qualification_nodes]

    raw_payload = {
        "job_id": external_job_id,
        "title": title,
        "company": company_name,
        "locations": locations,
        "detail_path": urlsplit(canonical_url).path,
        "minimum_qualifications": qualifications,
    }
    try:
        return NormalizedJob(
            external_job_id=external_job_id,
            title=title,
            location=locations,
            department=[],
            url=canonical_url,
            description=None,
            raw_payload=raw_payload,
        )
    except ValidationError as exc:
        raise ParsingError(f"invalid Google job card at index {index}: {exc}") from exc


def parse_google_page(html: str) -> ParsedGooglePage:
    """Parse one server-rendered Google Careers results page without I/O."""
    if not isinstance(html, str) or not html.strip():
        raise _UnexpectedGooglePageError("Google Careers page must be nonempty HTML text")

    range_match = _RANGE_PATTERN.search(html)
    if range_match is None:
        raise _UnexpectedGooglePageError("Google Careers page lacks result-range metadata")
    range_start, range_end, reported_count = (
        int(value.replace(",", "")) for value in range_match.groups()
    )

    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("ul.spHGqe > li.lLd3Je")
    jobs = tuple(_parse_google_card(card, index) for index, card in enumerate(cards))

    expected_items = 0 if reported_count == 0 else range_end - range_start + 1
    if range_start < 0 or range_end < range_start or expected_items != len(jobs):
        raise IncompleteCollectionError(
            "Google result range does not match the number of rendered job cards"
        )
    if reported_count == 0 and (range_start != 0 or range_end != 0):
        raise IncompleteCollectionError("Google empty results must report range 0 to 0")
    if reported_count > 0 and (range_start < 1 or range_end > reported_count):
        raise IncompleteCollectionError("Google result range falls outside its reported count")

    next_link = soup.select_one('a[href][aria-label="Go to next page"]')
    next_url: str | None = None
    if next_link is not None:
        href = next_link.get("href")
        if not isinstance(href, str):
            raise ParsingError("Google next-page link has an invalid URL")
        next_url = urljoin(BASE_URL, href)

    return ParsedGooglePage(
        jobs=jobs,
        range_start=range_start,
        range_end=range_end,
        reported_count=reported_count,
        next_url=next_url,
    )


def _validate_next_url(next_url: str, expected_page: int) -> str:
    parsed = urlsplit(next_url)
    if parsed.scheme != "https" or parsed.netloc != "www.google.com":
        raise IncompleteCollectionError("Google next-page link left the official careers host")
    if parsed.path != "/about/careers/applications/jobs/results":
        raise IncompleteCollectionError("Google next-page link changed the careers results path")
    query_values = httpx.QueryParams(parsed.query)
    if query_values.get("page") != str(expected_page):
        raise IncompleteCollectionError("Google next-page link did not advance sequentially")
    return next_url


class GoogleScraper:
    """Collect all server-rendered pages from Google Careers."""

    def __init__(
        self,
        company: GoogleCompany,
        *,
        max_pages: int = 250,
        page_delay_seconds: float = 0.25,
        page_parse_attempts: int = 2,
        page_retry_delay_seconds: float = 1.0,
        retry_policy: HttpRetryPolicy | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_pages < 1:
            raise ValueError("Google max_pages must be at least 1")
        if page_delay_seconds < 0:
            raise ValueError("Google page_delay_seconds cannot be negative")
        if page_parse_attempts < 1 or page_parse_attempts > 3:
            raise ValueError("Google page_parse_attempts must be between 1 and 3")
        if page_retry_delay_seconds < 0:
            raise ValueError("Google page_retry_delay_seconds cannot be negative")
        self.company = company
        self.max_pages = max_pages
        self.page_delay_seconds = page_delay_seconds
        self.page_parse_attempts = page_parse_attempts
        self.page_retry_delay_seconds = page_retry_delay_seconds
        self.retry_policy = retry_policy or HttpRetryPolicy()
        self.sleep = sleep

    @property
    def canonical_url(self) -> str:
        return RESULTS_URL

    def _retrieve_page(
        self, client: httpx.Client, url: str
    ) -> tuple[httpx.Response, ParsedGooglePage, int]:
        for attempt in range(1, self.page_parse_attempts + 1):
            response = request_with_retry(
                client,
                "GET",
                url,
                policy=self.retry_policy,
                headers={"Accept": "text/html", "User-Agent": USER_AGENT},
            )
            try:
                return response, parse_google_page(response.text), attempt - 1
            except _UnexpectedGooglePageError:
                if attempt == self.page_parse_attempts:
                    raise
                self.sleep(self.page_retry_delay_seconds)
        raise AssertionError("page parse retry loop terminated without returning or raising")

    def collect(self, client: httpx.Client) -> CollectionResult:
        all_jobs: list[NormalizedJob] = []
        pages: list[PageMetadata] = []
        reported_count: int | None = None
        next_url = f"{RESULTS_URL}?hl=en&page=1"
        seen_urls: set[str] = set()
        seen_page_ids: set[tuple[str, ...]] = set()
        transient_page_retries = 0

        for page_number in range(1, self.max_pages + 1):
            if next_url in seen_urls:
                raise IncompleteCollectionError("Google returned a repeated next-page URL")
            seen_urls.add(next_url)

            response, parsed_page, page_retries = self._retrieve_page(client, next_url)
            transient_page_retries += page_retries

            if reported_count is None:
                reported_count = parsed_page.reported_count
            elif parsed_page.reported_count != reported_count:
                raise IncompleteCollectionError("Google reported count changed during pagination")

            expected_start = 0 if reported_count == 0 else len(all_jobs) + 1
            if parsed_page.range_start != expected_start:
                raise IncompleteCollectionError(
                    "Google result range did not continue from the prior page"
                )

            page_ids = tuple(job.external_job_id for job in parsed_page.jobs)
            if page_ids and page_ids in seen_page_ids:
                raise IncompleteCollectionError("Google returned a repeated job page")
            seen_page_ids.add(page_ids)

            pages.append(
                PageMetadata(
                    page_number=page_number,
                    request_url=str(response.request.url),
                    item_count=len(parsed_page.jobs),
                    cursor=page_number,
                )
            )
            all_jobs.extend(parsed_page.jobs)

            if len(all_jobs) == reported_count:
                if parsed_page.next_url is not None:
                    raise IncompleteCollectionError(
                        "Google exposed another page after the reported inventory ended"
                    )
                break
            if len(all_jobs) > reported_count:
                raise IncompleteCollectionError(
                    f"Google returned {len(all_jobs)} jobs after reporting {reported_count}"
                )
            if parsed_page.next_url is None:
                raise IncompleteCollectionError(
                    f"Google pagination ended after {len(all_jobs)} of {reported_count} jobs"
                )
            next_url = _validate_next_url(parsed_page.next_url, page_number + 1)
            self.sleep(self.page_delay_seconds)
        else:
            raise IncompleteCollectionError(
                f"Google collection exceeded the {self.max_pages}-page safety bound"
            )

        assert reported_count is not None
        source = SourceMetadata(
            adapter="google",
            source_identifier=self.company.slug,
            canonical_url=self.canonical_url,
            reported_job_count=reported_count,
            pages=pages,
            metadata={
                "rendering": "server_html",
                "language": "en",
                "page_delay_seconds": self.page_delay_seconds,
                "transient_page_retries": transient_page_retries,
            },
        )
        try:
            return CollectionResult(source=source, jobs=all_jobs)
        except ValidationError as exc:
            raise IncompleteCollectionError(f"invalid complete Google collection: {exc}") from exc
