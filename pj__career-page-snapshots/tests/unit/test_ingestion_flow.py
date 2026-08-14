"""Deterministic tests for Prefect ingestion orchestration."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import psycopg
import pytest
from prefect.states import Failed
from pydantic import SecretStr

import career_page_snapshots.flows.ingestion as ingestion
from career_page_snapshots.config import CompaniesConfig, GreenhouseCompany, RuntimeSettings
from career_page_snapshots.database import SnapshotRecord, WriteResult
from career_page_snapshots.models import CollectionResult, PageMetadata, SourceMetadata
from career_page_snapshots.scrapers.base import ParsingError, RetrievalError


class FakeFuture:
    def __init__(self, *, value: object = None, error: Exception | None = None) -> None:
        self.value = value
        self.error = error
        self.waited = False

    def result(self) -> object:
        if self.error is not None:
            raise self.error
        return self.value

    def wait(self) -> None:
        self.waited = True


def _company(name: str = "Example") -> GreenhouseCompany:
    return GreenhouseCompany(name=name, scraper="greenhouse", slug=name.casefold())


def _empty_collection() -> CollectionResult:
    url = "https://boards-api.greenhouse.io/v1/boards/example/jobs"
    return CollectionResult(
        source=SourceMetadata(
            adapter="greenhouse",
            source_identifier="example",
            canonical_url=url,
            reported_job_count=0,
            pages=[PageMetadata(page_number=1, request_url=url, item_count=0)],
        ),
        jobs=[],
    )


def _write_result(company_name: str, collection_key: str, captured_at: datetime) -> WriteResult:
    snapshot = SnapshotRecord.from_collection(
        company_name=company_name,
        collection_key=collection_key,
        captured_at=captured_at,
        collection=_empty_collection(),
    )
    return WriteResult(snapshot=snapshot, inserted=True)


def _configure_flow(
    monkeypatch: pytest.MonkeyPatch,
    companies: list[GreenhouseCompany],
    *,
    flow_run_id: UUID,
) -> None:
    settings = RuntimeSettings(
        DATABASE_URL="postgresql://user:password@localhost/database",
        COMPANIES_FILE="companies.yml",
        HTTP_TIMEOUT_SECONDS=12,
    )
    monkeypatch.setattr(ingestion, "load_runtime_settings", lambda: settings)
    monkeypatch.setattr(
        ingestion,
        "load_companies",
        lambda _path: CompaniesConfig(companies=companies),
    )
    monkeypatch.setattr(
        ingestion,
        "get_run_context",
        lambda: SimpleNamespace(flow_run=SimpleNamespace(id=flow_run_id)),
    )
    monkeypatch.setattr(
        ingestion,
        "get_run_logger",
        lambda: SimpleNamespace(info=lambda *args: None, error=lambda *args: None),
    )


def test_flow_reports_total_success_and_preserves_run_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    companies = [_company("First"), _company("Second")]
    flow_run_id = uuid4()
    _configure_flow(monkeypatch, companies, flow_run_id=flow_run_id)
    collections: dict[str, FakeFuture] = {}
    persistence_calls: list[tuple[str, str, datetime]] = []

    def submit_collection(company: GreenhouseCompany, _timeout: float) -> FakeFuture:
        future = FakeFuture(value=_empty_collection())
        collections[company.name] = future
        return future

    def submit_persistence(
        database_url: SecretStr,
        company_name: str,
        collection_key: str,
        captured_at: datetime,
        collection_future: FakeFuture,
    ) -> FakeFuture:
        assert str(database_url) == "**********"
        assert collection_future is collections[company_name]
        persistence_calls.append((company_name, collection_key, captured_at))
        return FakeFuture(value=_write_result(company_name, collection_key, captured_at))

    monkeypatch.setattr(ingestion.collect_company, "submit", submit_collection)
    monkeypatch.setattr(ingestion.persist_company, "submit", submit_persistence)

    summary = ingestion.career_page_snapshots_flow.fn().result()

    assert summary.status == "completed"
    assert summary.flow_run_id == flow_run_id
    assert [item.company_name for item in summary.successes] == ["First", "Second"]
    assert summary.failures == ()
    assert {call[1] for call in persistence_calls} == {str(flow_run_id)}
    assert {call[2] for call in persistence_calls} == {summary.captured_at}


def test_flow_completes_with_errors_and_keeps_successful_company(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    companies = [_company("Broken"), _company("Working")]
    _configure_flow(monkeypatch, companies, flow_run_id=uuid4())
    collection_futures = {
        "Broken": FakeFuture(error=ParsingError("bad source payload")),
        "Working": FakeFuture(value=_empty_collection()),
    }

    def submit_persistence(
        _database_url: str,
        company_name: str,
        collection_key: str,
        captured_at: datetime,
        _collection_future: FakeFuture,
    ) -> FakeFuture:
        if company_name == "Broken":
            return FakeFuture(error=RuntimeError("upstream failed"))
        return FakeFuture(value=_write_result(company_name, collection_key, captured_at))

    monkeypatch.setattr(
        ingestion.collect_company,
        "submit",
        lambda company, _timeout: collection_futures[company.name],
    )
    monkeypatch.setattr(ingestion.persist_company, "submit", submit_persistence)

    state = ingestion.career_page_snapshots_flow.fn()
    summary = state.result()

    assert state.is_completed()
    assert summary.status == "completed_with_errors"
    assert [item.company_name for item in summary.successes] == ["Working"]
    assert summary.failures[0].company_name == "Broken"
    assert summary.failures[0].stage == "collection"
    assert collection_futures["Broken"].waited is False


def test_flow_is_completed_when_every_company_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    companies = [_company("First"), _company("Second")]
    _configure_flow(monkeypatch, companies, flow_run_id=uuid4())
    downstream: list[FakeFuture] = []

    monkeypatch.setattr(
        ingestion.collect_company,
        "submit",
        lambda company, _timeout: FakeFuture(error=ParsingError(f"bad {company.name}")),
    )

    def submit_persistence(*_args: object) -> FakeFuture:
        future = FakeFuture(error=RuntimeError("upstream failed"))
        downstream.append(future)
        return future

    monkeypatch.setattr(ingestion.persist_company, "submit", submit_persistence)

    state = ingestion.career_page_snapshots_flow.fn()
    summary = state.result()

    assert state.is_completed()
    assert summary.status == "completed_with_errors"
    assert summary.successes == ()
    assert [failure.company_name for failure in summary.failures] == ["First", "Second"]
    assert all(failure.stage == "collection" for failure in summary.failures)
    assert all(future.waited for future in downstream)


def test_persistence_failure_is_isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    company = _company()
    _configure_flow(monkeypatch, [company], flow_run_id=uuid4())
    monkeypatch.setattr(
        ingestion.collect_company,
        "submit",
        lambda *_args: FakeFuture(value=_empty_collection()),
    )
    monkeypatch.setattr(
        ingestion.persist_company,
        "submit",
        lambda *_args: FakeFuture(error=psycopg.OperationalError("database unavailable")),
    )

    summary = ingestion.career_page_snapshots_flow.fn().result()

    assert summary.status == "completed_with_errors"
    assert summary.successes == ()
    assert summary.failures[0].stage == "persistence"


def test_empty_collection_persists_zero_job_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    collection = _empty_collection()
    captured_at = datetime(2026, 8, 12, tzinfo=UTC)
    persisted: list[SnapshotRecord] = []

    def fake_persist(_database_url: str, snapshot: SnapshotRecord) -> WriteResult:
        persisted.append(snapshot)
        return WriteResult(snapshot=snapshot, inserted=True)

    monkeypatch.setattr(ingestion, "persist_snapshot", fake_persist)

    result = ingestion.persist_company.fn(
        SecretStr("postgresql://unused"),
        "Example",
        "flow-run-id",
        captured_at,
        collection,
    )

    assert result.snapshot.job_count == 0
    assert result.snapshot.payload.jobs == ()
    assert persisted[0].captured_at == captured_at
    assert persisted[0].collection_key == "flow-run-id"


def test_collection_task_dispatches_to_configured_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = _empty_collection()
    client = object()
    client_options: dict[str, object] = {}

    class ClientContext:
        def __enter__(self) -> object:
            return client

        def __exit__(self, *_args: object) -> None:
            return None

    def make_client(**kwargs: object) -> ClientContext:
        client_options.update(kwargs)
        return ClientContext()

    class FakeScraper:
        def collect(self, received_client: object) -> CollectionResult:
            assert received_client is client
            return expected

    monkeypatch.setattr(ingestion.httpx, "Client", make_client)
    monkeypatch.setattr(ingestion, "build_scraper", lambda _company: FakeScraper())

    result = ingestion.collect_company.fn(_company(), 12.5)

    assert result is expected
    assert client_options == {"timeout": 12.5, "follow_redirects": True}


def test_task_retry_filters_are_transient_only() -> None:
    request = httpx.Request("GET", "https://example.com")
    transient = RetrievalError("transient")
    transient.__cause__ = httpx.ConnectError("connection lost", request=request)
    ordinary_404 = RetrievalError("not found")
    ordinary_404.__cause__ = httpx.HTTPStatusError(
        "not found",
        request=request,
        response=httpx.Response(404, request=request),
    )

    assert ingestion._retry_retrieval_failure(None, None, Failed(data=transient))
    assert not ingestion._retry_retrieval_failure(None, None, Failed(data=ordinary_404))
    assert not ingestion._retry_retrieval_failure(None, None, Failed(data=ParsingError("x")))
    assert ingestion._retry_database_failure(None, None, Failed(data=psycopg.OperationalError("x")))
    authentication_error = psycopg.errors.InvalidPassword("bad credentials")
    assert not ingestion._retry_database_failure(None, None, Failed(data=authentication_error))
    assert not ingestion._retry_database_failure(None, None, Failed(data=ValueError("x")))
