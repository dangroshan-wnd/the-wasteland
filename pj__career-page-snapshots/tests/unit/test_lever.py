import json
from pathlib import Path

import httpx
import pytest

from career_page_snapshots.config import LeverCompany
from career_page_snapshots.scrapers.base import IncompleteCollectionError, ParsingError
from career_page_snapshots.scrapers.lever import LeverScraper, parse_lever_payload

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def load_fixture(name: str) -> list[dict[str, object]]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_parse_lever_fixture_and_optional_fields() -> None:
    jobs = parse_lever_payload(load_fixture("lever_page_1.json"))

    assert jobs[0].external_job_id == "lever-101"
    assert jobs[0].location == ("New York, NY", "Washington, DC")
    assert jobs[0].department == ("Engineering",)
    assert jobs[1].location == ("London, United Kingdom",)
    assert jobs[1].description is None


def test_parse_lever_empty_page() -> None:
    assert parse_lever_payload([]) == ()


def test_parse_lever_rejects_malformed_payload() -> None:
    with pytest.raises(ParsingError, match="must be an array"):
        parse_lever_payload({"postings": []})


def test_lever_scraper_collects_until_short_page() -> None:
    first_page = load_fixture("lever_page_1.json")
    second_page = load_fixture("lever_page_2.json")
    observed_skips: list[str] = []
    observed_delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed_skips.append(request.url.params["skip"])
        payload = first_page if request.url.params["skip"] == "0" else second_page
        return httpx.Response(200, json=payload)

    company = LeverCompany(name="Palantir", scraper="lever", slug="palantir")
    scraper = LeverScraper(
        company,
        page_size=2,
        page_delay_seconds=0.5,
        sleep=observed_delays.append,
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = scraper.collect(client)

    assert observed_skips == ["0", "2"]
    assert observed_delays == [0.5]
    assert [job.external_job_id for job in result.jobs] == [
        "lever-101",
        "lever-102",
        "lever-103",
    ]
    assert [page.item_count for page in result.source.pages] == [2, 1]


def test_lever_scraper_accepts_empty_board() -> None:
    company = LeverCompany(name="Example", scraper="lever", slug="example")
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[]))
    ) as client:
        result = LeverScraper(company, page_size=2, page_delay_seconds=0).collect(client)

    assert result.job_count == 0
    assert result.source.pages[0].item_count == 0


def test_lever_scraper_rejects_repeated_page() -> None:
    page = load_fixture("lever_page_1.json")
    company = LeverCompany(name="Example", scraper="lever", slug="example")
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=page))
    ) as client:
        with pytest.raises(IncompleteCollectionError, match="repeated page"):
            LeverScraper(company, page_size=2, page_delay_seconds=0).collect(client)
