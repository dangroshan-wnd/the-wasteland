import json
from pathlib import Path

import httpx
import pytest

from career_page_snapshots.config import EightfoldCompany
from career_page_snapshots.scrapers.base import IncompleteCollectionError, ParsingError
from career_page_snapshots.scrapers.eightfold import (
    EightfoldScraper,
    parse_eightfold_detail_description,
    parse_eightfold_payload,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def load_fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def make_company() -> EightfoldCompany:
    return EightfoldCompany(
        name="Netflix",
        scraper="eightfold",
        slug="netflix",
        careers_host="explore.jobs.netflix.net",
        domain="netflix.com",
    )


def test_parse_eightfold_fixture_and_optional_fields() -> None:
    jobs, reported_count = parse_eightfold_payload(load_fixture("eightfold_page_1.json"))

    assert reported_count == 3
    assert jobs[0].external_job_id == "201"
    assert jobs[0].description is None
    assert jobs[1].location == ("Los Angeles, California", "New York, New York")


def test_parse_eightfold_falls_back_to_posting_name_and_location() -> None:
    jobs, _ = parse_eightfold_payload(load_fixture("eightfold_page_2.json"))

    assert jobs[0].title == "Administrative Assistant"
    assert jobs[0].location == ("London, United Kingdom",)
    assert jobs[0].department == ()


def test_parse_optional_eightfold_detail_description() -> None:
    description = parse_eightfold_detail_description(load_fixture("eightfold_detail.json"))

    assert description == "<p>Build streaming systems at global scale.</p>"


def test_parse_eightfold_rejects_malformed_payload() -> None:
    with pytest.raises(ParsingError, match="positions array"):
        parse_eightfold_payload({"count": 0})


def test_eightfold_scraper_collects_reported_inventory() -> None:
    pages = {
        "0": load_fixture("eightfold_page_1.json"),
        "2": load_fixture("eightfold_page_2.json"),
    }
    observed_starts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        start = request.url.params["start"]
        observed_starts.append(start)
        assert request.url.params["domain"] == "netflix.com"
        return httpx.Response(200, json=pages[start])

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = EightfoldScraper(make_company(), page_size=2, page_delay_seconds=0).collect(client)

    assert observed_starts == ["0", "2"]
    assert result.job_count == 3
    assert result.source.reported_job_count == 3
    assert result.source.metadata["detail_enrichment"] is False


def test_eightfold_scraper_accepts_empty_inventory() -> None:
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"count": 0, "positions": []})
        )
    ) as client:
        result = EightfoldScraper(make_company()).collect(client)

    assert result.job_count == 0


def test_eightfold_scraper_rejects_count_change() -> None:
    first = load_fixture("eightfold_page_1.json")
    second = load_fixture("eightfold_page_2.json")
    second["count"] = 4

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=first if request.url.params["start"] == "0" else second)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(IncompleteCollectionError, match="count changed"):
            EightfoldScraper(
                make_company(), page_size=2, page_delay_seconds=0, inventory_attempts=1
            ).collect(client)


def test_eightfold_scraper_rejects_early_empty_page() -> None:
    first = load_fixture("eightfold_page_1.json")

    def handler(request: httpx.Request) -> httpx.Response:
        payload = first if request.url.params["start"] == "0" else {"count": 3, "positions": []}
        return httpx.Response(200, json=payload)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(IncompleteCollectionError, match="pagination ended"):
            EightfoldScraper(
                make_company(), page_size=2, page_delay_seconds=0, inventory_attempts=1
            ).collect(client)


def test_eightfold_scraper_rejects_repeated_page() -> None:
    page = load_fixture("eightfold_page_1.json")

    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=page))
    ) as client:
        with pytest.raises(IncompleteCollectionError, match="repeated page"):
            EightfoldScraper(
                make_company(), page_size=2, page_delay_seconds=0, inventory_attempts=1
            ).collect(client)


def test_eightfold_restarts_after_transient_pagination_drift() -> None:
    first = load_fixture("eightfold_page_1.json")
    final = load_fixture("eightfold_page_2.json")
    drifted_first = load_fixture("eightfold_page_1.json")
    drifted_first["count"] = 4
    drifted_final = {
        "count": 4,
        "positions": [final["positions"][0], first["positions"][0]],
    }
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        start = request.url.params["start"]
        requests.append(start)
        if len(requests) <= 2:
            payload = drifted_first if start == "0" else drifted_final
            return httpx.Response(200, json=payload)
        return httpx.Response(200, json=first if start == "0" else final)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = EightfoldScraper(
            make_company(),
            page_size=2,
            page_delay_seconds=0,
            inventory_retry_delay_seconds=0,
        ).collect(client)

    assert requests == ["0", "2", "0", "2"]
    assert result.job_count == 3
    assert result.source.metadata["inventory_attempt"] == 2
