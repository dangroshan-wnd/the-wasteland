from pathlib import Path

import httpx
import pytest

from career_page_snapshots.config import GoogleCompany
from career_page_snapshots.scrapers.base import IncompleteCollectionError, ParsingError
from career_page_snapshots.scrapers.google import GoogleScraper, parse_google_page

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def load_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def make_company() -> GoogleCompany:
    return GoogleCompany(name="Google", scraper="google", slug="google")


def test_parse_google_first_page_fixture() -> None:
    page = parse_google_page(load_fixture("google_page_1.html"))

    assert page.reported_count == 5
    assert page.range_start == 1
    assert page.range_end == 2
    assert page.next_url is not None and page.next_url.endswith("page=2")
    assert page.jobs[0].external_job_id == "301"
    assert page.jobs[0].location == ("New York, NY, USA", "Atlanta, GA, USA")
    assert page.jobs[0].url.endswith("/301-software-engineer-iii")
    assert page.jobs[0].raw_payload["company"] == "Google"  # type: ignore[index]


def test_parse_google_empty_results() -> None:
    page = parse_google_page(load_fixture("google_empty.html"))

    assert page.reported_count == 0
    assert page.jobs == ()
    assert page.next_url is None


def test_parse_google_rejects_missing_range() -> None:
    with pytest.raises(ParsingError, match="lacks result-range"):
        parse_google_page("<html><ul class='spHGqe'></ul></html>")


def test_parse_google_rejects_card_count_mismatch() -> None:
    html = load_fixture("google_page_1.html").replace(
        "Showing 1 to 2 of 5 rows", "Showing 1 to 3 of 5 rows"
    )

    with pytest.raises(IncompleteCollectionError, match="does not match"):
        parse_google_page(html)


def test_google_scraper_collects_all_server_rendered_pages() -> None:
    pages = {
        "1": load_fixture("google_page_1.html"),
        "2": load_fixture("google_page_2.html"),
        "3": load_fixture("google_page_3.html"),
    }
    observed_pages: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params["page"]
        assert request.url.params["sort_by"] == "date"
        observed_pages.append(page)
        return httpx.Response(200, text=pages[page], headers={"content-type": "text/html"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = GoogleScraper(make_company(), page_delay_seconds=0).collect(client)

    assert observed_pages == ["1", "2", "3"]
    assert result.job_count == 5
    assert result.source.reported_job_count == 5
    assert [page.item_count for page in result.source.pages] == [2, 2, 1]
    assert result.source.metadata["sort_by"] == "date"
    assert result.source.metadata["inventory_attempt"] == 1


def test_google_scraper_retries_inventory_with_duplicate_job_ids() -> None:
    pages = {
        "1": load_fixture("google_page_1.html"),
        "2": load_fixture("google_page_2.html"),
        "3": load_fixture("google_page_3.html"),
    }
    drifting_second_page = pages["2"].replace("303-data-scientist", "301-data-scientist")
    observed_pages: list[str] = []
    inventory_attempt = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal inventory_attempt
        page = request.url.params["page"]
        if page == "1":
            inventory_attempt += 1
        observed_pages.append(page)
        html = drifting_second_page if inventory_attempt == 1 and page == "2" else pages[page]
        return httpx.Response(200, text=html)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = GoogleScraper(
            make_company(),
            page_delay_seconds=0,
            inventory_retry_delay_seconds=0,
        ).collect(client)

    assert observed_pages == ["1", "2", "3", "1", "2", "3"]
    assert result.job_count == 5
    assert result.source.metadata["inventory_attempt"] == 2


def test_google_scraper_accepts_empty_inventory() -> None:
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text=load_fixture("google_empty.html"))
        )
    ) as client:
        result = GoogleScraper(make_company(), page_delay_seconds=0).collect(client)

    assert result.job_count == 0


def test_google_scraper_retries_temporary_non_results_page() -> None:
    pages = {
        "1": load_fixture("google_page_1.html"),
        "2": load_fixture("google_page_2.html"),
        "3": load_fixture("google_page_3.html"),
    }
    observed_pages: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params["page"]
        observed_pages.append(page)
        if len(observed_pages) == 1:
            return httpx.Response(200, text="<html><title>Temporary response</title></html>")
        return httpx.Response(200, text=pages[page])

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = GoogleScraper(
            make_company(), page_delay_seconds=0, page_retry_delay_seconds=0
        ).collect(client)

    assert observed_pages == ["1", "1", "2", "3"]
    assert result.job_count == 5
    assert result.source.metadata["transient_page_retries"] == 1


def test_google_scraper_rejects_changed_count() -> None:
    first = load_fixture("google_page_1.html")
    second = load_fixture("google_page_2.html").replace("of 5 rows", "of 6 rows")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=first if request.url.params["page"] == "1" else second)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(IncompleteCollectionError, match="count changed"):
            GoogleScraper(
                make_company(),
                page_delay_seconds=0,
                inventory_retry_delay_seconds=0,
            ).collect(client)


def test_google_scraper_rejects_page_safety_bound() -> None:
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text=load_fixture("google_page_1.html"))
        )
    ) as client:
        with pytest.raises(IncompleteCollectionError, match="safety bound"):
            GoogleScraper(make_company(), max_pages=1, page_delay_seconds=0).collect(client)


def test_google_scraper_rejects_repeated_job_page() -> None:
    first = load_fixture("google_page_1.html")
    repeated = first.replace("Showing 1 to 2", "Showing 3 to 4").replace("page=2", "page=3")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=first if request.url.params["page"] == "1" else repeated)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(IncompleteCollectionError, match="repeated job page"):
            GoogleScraper(
                make_company(),
                page_delay_seconds=0,
                inventory_retry_delay_seconds=0,
            ).collect(client)


def test_google_scraper_rejects_nonsequential_next_link() -> None:
    first = load_fixture("google_page_1.html").replace("page=2", "page=4")

    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text=first))
    ) as client:
        with pytest.raises(IncompleteCollectionError, match="did not advance sequentially"):
            GoogleScraper(make_company(), page_delay_seconds=0).collect(client)
