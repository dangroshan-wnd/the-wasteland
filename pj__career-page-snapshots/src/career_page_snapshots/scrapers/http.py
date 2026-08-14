"""Shared bounded retry policy for source HTTP requests."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from career_page_snapshots.scrapers.base import RetrievalError

RETRYABLE_STATUS_CODES = frozenset({408, 429})


@dataclass(frozen=True, slots=True)
class HttpRetryPolicy:
    """Bounded exponential-backoff settings shared by all V1 adapters."""

    max_attempts: int = 3
    initial_backoff_seconds: float = 1.0
    maximum_backoff_seconds: float = 8.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.initial_backoff_seconds < 0:
            raise ValueError("initial_backoff_seconds cannot be negative")
        if self.maximum_backoff_seconds < self.initial_backoff_seconds:
            raise ValueError("maximum_backoff_seconds cannot be less than initial_backoff_seconds")

    def backoff_after_failure(self, failed_attempt: int) -> float:
        """Return the bounded delay after a failed one-indexed attempt."""
        if failed_attempt < 1 or failed_attempt >= self.max_attempts:
            raise ValueError("failed_attempt must identify a retryable attempt")
        delay = self.initial_backoff_seconds * (2 ** (failed_attempt - 1))
        return min(delay, self.maximum_backoff_seconds)


def is_retryable_http_error(exc: BaseException) -> bool:
    """Classify only transient transport and documented transient HTTP failures."""
    if isinstance(exc, httpx.TransportError):
        return True
    if not isinstance(exc, httpx.HTTPStatusError):
        return False

    status_code = exc.response.status_code
    return status_code in RETRYABLE_STATUS_CODES or 500 <= status_code <= 599


def request_with_retry(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    policy: HttpRetryPolicy,
    sleep: Callable[[float], None] = time.sleep,
    **request_kwargs: object,
) -> httpx.Response:
    """Execute one status-checked HTTP request under the shared retry policy."""
    for attempt in range(1, policy.max_attempts + 1):
        try:
            response = client.request(method, url, **request_kwargs)
            response.raise_for_status()
            return response
        except httpx.HTTPError as exc:
            if attempt == policy.max_attempts or not is_retryable_http_error(exc):
                raise RetrievalError(
                    f"{method.upper()} {url} failed after {attempt} attempt(s)"
                ) from exc
            sleep(policy.backoff_after_failure(attempt))

    raise AssertionError("retry loop terminated without returning or raising")
