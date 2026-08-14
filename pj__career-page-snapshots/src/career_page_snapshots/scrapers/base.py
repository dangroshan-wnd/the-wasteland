"""Common scraper protocol and domain errors."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import httpx

from career_page_snapshots.models import CollectionResult


class ScraperError(Exception):
    """Base error for a company collection failure."""


class RetrievalError(ScraperError):
    """A source could not be retrieved completely."""


class ParsingError(ScraperError):
    """A retrieved source payload violated its deterministic parser contract."""


class IncompleteCollectionError(ScraperError):
    """Pagination or source counts show that only a partial inventory was collected."""


@runtime_checkable
class Scraper(Protocol):
    """Small interface implemented by each configured source adapter."""

    def collect(self, client: httpx.Client) -> CollectionResult:
        """Retrieve and parse one complete company inventory."""
        ...
