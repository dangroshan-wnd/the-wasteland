import json
from pathlib import Path

import httpx
import pytest

from career_page_snapshots.config import GreenhouseCompany
from career_page_snapshots.scrapers.base import IncompleteCollectionError, ParsingError
from career_page_snapshots.scrapers.greenhouse import GreenhouseScraper, parse_greenhouse_payload

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def load_fixture() -> dict[str, object]:
    return json.loads((FIXTURES / "greenhouse_jobs.json").read_text(encoding="utf-8"))


def test_parse_greenhouse_fixture() -> None:
    jobs, reported_count = parse_greenhouse_payload(load_fixture())

    assert reported_count == 2
    assert jobs[0].external_job_id == "101"
    assert jobs[0].location == ("New York or Remote",)
    assert jobs[0].department == ("Engineering",)
    assert jobs[0].description == "<p>Build reliable systems.</p>"
    assert jobs[1].description is None


def test_parse_greenhouse_empty_board() -> None:
    jobs, reported_count = parse_greenhouse_payload({"jobs": [], "meta": {"total": 0}})

    assert jobs == ()
    assert reported_count == 0


def test_parse_greenhouse_rejects_malformed_required_job() -> None:
    payload = load_fixture()
    payload["jobs"][0].pop("title")  # type: ignore[index,union-attr]

    with pytest.raises(ParsingError, match="invalid Greenhouse job"):
        parse_greenhouse_payload(payload)


def test_parse_greenhouse_rejects_count_mismatch() -> None:
    payload = load_fixture()
    payload["meta"]["total"] = 3  # type: ignore[index]

    with pytest.raises(IncompleteCollectionError, match="reported 3 jobs"):
        parse_greenhouse_payload(payload)


def test_greenhouse_scraper_collects_one_complete_page() -> None:
    payload = load_fixture()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/boards/kalshi/jobs"
        assert request.url.params["content"] == "true"
        return httpx.Response(200, json=payload)

    company = GreenhouseCompany(name="Kalshi", scraper="greenhouse", slug="kalshi")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = GreenhouseScraper(company).collect(client)

    assert result.job_count == 2
    assert result.source.reported_job_count == 2
    assert result.source.pages[0].item_count == 2
    assert result.source.metadata == {"content": True}
