import httpx
import pytest

from career_page_snapshots.scrapers.base import RetrievalError
from career_page_snapshots.scrapers.http import (
    HttpRetryPolicy,
    is_retryable_http_error,
    request_with_retry,
)


def make_status_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://jobs.example.com")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError("request failed", request=request, response=response)


@pytest.mark.parametrize("status_code", [408, 429, 500, 503, 599])
def test_retryable_http_statuses(status_code: int) -> None:
    assert is_retryable_http_error(make_status_error(status_code))


@pytest.mark.parametrize("status_code", [400, 401, 403, 404, 409, 422])
def test_non_retryable_http_statuses(status_code: int) -> None:
    assert not is_retryable_http_error(make_status_error(status_code))


def test_transport_errors_are_retryable() -> None:
    request = httpx.Request("GET", "https://jobs.example.com")

    assert is_retryable_http_error(httpx.ReadTimeout("timed out", request=request))


def test_deterministic_errors_are_not_retryable() -> None:
    assert not is_retryable_http_error(ValueError("bad configuration"))


def test_retry_policy_uses_bounded_exponential_backoff() -> None:
    policy = HttpRetryPolicy(
        max_attempts=5,
        initial_backoff_seconds=1.5,
        maximum_backoff_seconds=4,
    )

    assert [policy.backoff_after_failure(attempt) for attempt in range(1, 5)] == [1.5, 3, 4, 4]


@pytest.mark.parametrize(
    "values",
    [
        {"max_attempts": 0},
        {"initial_backoff_seconds": -1},
        {"initial_backoff_seconds": 2, "maximum_backoff_seconds": 1},
    ],
)
def test_retry_policy_rejects_invalid_bounds(values: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        HttpRetryPolicy(**values)


@pytest.mark.parametrize("attempt", [0, 3])
def test_retry_policy_rejects_non_retryable_attempt_numbers(attempt: int) -> None:
    policy = HttpRetryPolicy(max_attempts=3)

    with pytest.raises(ValueError, match="retryable attempt"):
        policy.backoff_after_failure(attempt)


def test_request_with_retry_retries_transport_failure() -> None:
    attempts = 0
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ReadTimeout("timed out", request=request)
        return httpx.Response(200, json={"ok": True})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        response = request_with_retry(
            client,
            "GET",
            "https://jobs.example.com",
            policy=HttpRetryPolicy(),
            sleep=delays.append,
        )

    assert response.json() == {"ok": True}
    assert attempts == 2
    assert delays == [1.0]


def test_request_with_retry_does_not_retry_ordinary_4xx() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(404)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RetrievalError, match="after 1 attempt"):
            request_with_retry(
                client,
                "GET",
                "https://jobs.example.com",
                policy=HttpRetryPolicy(),
                sleep=lambda delay: None,
            )

    assert attempts == 1
