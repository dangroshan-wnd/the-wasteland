"""Prefect orchestration for complete career-page snapshots."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

import httpx
import psycopg
from prefect import flow, get_run_logger, task
from prefect.client.schemas.objects import TaskRun
from prefect.context import get_run_context
from prefect.futures import PrefectFuture
from prefect.states import Completed, State
from prefect.tasks import Task
from pydantic import BaseModel, ConfigDict, SecretStr

from career_page_snapshots.config import (
    Company,
    EightfoldCompany,
    GoogleCompany,
    GreenhouseCompany,
    LeverCompany,
    load_companies,
    load_runtime_settings,
)
from career_page_snapshots.database import SnapshotRecord, WriteResult, persist_snapshot
from career_page_snapshots.models import CollectionResult
from career_page_snapshots.scrapers.base import RetrievalError, Scraper
from career_page_snapshots.scrapers.eightfold import EightfoldScraper
from career_page_snapshots.scrapers.google import GoogleScraper
from career_page_snapshots.scrapers.greenhouse import GreenhouseScraper
from career_page_snapshots.scrapers.http import is_retryable_http_error
from career_page_snapshots.scrapers.lever import LeverScraper

_TRANSIENT_DATABASE_SQLSTATES = frozenset(
    {
        "40001",  # serialization_failure
        "40P01",  # deadlock_detected
        "53300",  # too_many_connections
        "53400",  # configuration_limit_exceeded
        "55P03",  # lock_not_available
        "57P01",  # admin_shutdown
        "57P02",  # crash_shutdown
        "57P03",  # cannot_connect_now
    }
)


class CompanySuccess(BaseModel):
    """One company snapshot that was durably persisted."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    company_name: str
    snapshot_id: UUID
    source_url: str
    job_count: int
    inserted: bool


class CompanyFailure(BaseModel):
    """One company failure isolated after dispatch."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    company_name: str
    stage: Literal["collection", "persistence"]
    error_type: str
    message: str


class FlowSummary(BaseModel):
    """Structured final result for a dispatched ingestion run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["completed", "completed_with_errors"]
    flow_run_id: UUID
    captured_at: datetime
    successes: tuple[CompanySuccess, ...]
    failures: tuple[CompanyFailure, ...]


def _failure_exception(state: State[Any]) -> BaseException | None:
    result = state.result(raise_on_failure=False)
    return result if isinstance(result, BaseException) else None


def _retry_retrieval_failure(_task: Task[..., Any], _task_run: TaskRun, state: State[Any]) -> bool:
    """Retry only exhausted source retrieval failures, never parsing failures."""
    exc = _failure_exception(state)
    return (
        isinstance(exc, RetrievalError)
        and exc.__cause__ is not None
        and is_retryable_http_error(exc.__cause__)
    )


def _retry_database_failure(_task: Task[..., Any], _task_run: TaskRun, state: State[Any]) -> bool:
    """Retry only connection-level database failures."""
    exc = _failure_exception(state)
    if not isinstance(exc, psycopg.OperationalError):
        return False
    return (
        exc.sqlstate is None
        or exc.sqlstate.startswith("08")
        or exc.sqlstate in _TRANSIENT_DATABASE_SQLSTATES
    )


def build_scraper(company: Company) -> Scraper:
    """Construct the concrete V1 adapter selected by validated configuration."""
    if isinstance(company, GreenhouseCompany):
        return GreenhouseScraper(company)
    if isinstance(company, LeverCompany):
        return LeverScraper(company)
    if isinstance(company, EightfoldCompany):
        return EightfoldScraper(company)
    if isinstance(company, GoogleCompany):
        return GoogleScraper(company)
    raise TypeError(f"unsupported company configuration: {type(company).__name__}")


@task(
    name="collect-company-career-page",
    retries=2,
    retry_delay_seconds=[5, 15],
    retry_condition_fn=_retry_retrieval_failure,
)
def collect_company(company: Company, http_timeout_seconds: float) -> CollectionResult:
    """Retrieve one complete company inventory using its configured adapter."""
    scraper = build_scraper(company)
    with httpx.Client(timeout=http_timeout_seconds, follow_redirects=True) as client:
        return scraper.collect(client)


@task(
    name="persist-company-snapshot",
    retries=2,
    retry_delay_seconds=[5, 15],
    retry_condition_fn=_retry_database_failure,
)
def persist_company(
    database_url: SecretStr,
    company_name: str,
    collection_key: str,
    captured_at: datetime,
    collection: CollectionResult,
) -> WriteResult:
    """Build and durably persist one idempotent company snapshot."""
    snapshot = SnapshotRecord.from_collection(
        company_name=company_name,
        collection_key=collection_key,
        captured_at=captured_at,
        collection=collection,
    )
    return persist_snapshot(database_url.get_secret_value(), snapshot)


def _safe_failure_message(exc: BaseException) -> str:
    message = str(exc).strip()
    return message or "No error message was provided."


def _company_failure(
    company_name: str, stage: Literal["collection", "persistence"], exc: BaseException
) -> CompanyFailure:
    return CompanyFailure(
        company_name=company_name,
        stage=stage,
        error_type=type(exc).__name__,
        message=_safe_failure_message(exc),
    )


@flow(name="career-page-snapshots")
def career_page_snapshots_flow() -> State[FlowSummary]:
    """Collect and persist every configured company with failure isolation."""
    settings = load_runtime_settings()
    companies = load_companies(settings.companies_file).companies
    context = get_run_context()
    flow_run_id = context.flow_run.id
    captured_at = datetime.now(UTC)
    collection_key = str(flow_run_id)
    database_url = SecretStr(str(settings.database_url))

    dispatched: list[
        tuple[Company, PrefectFuture[CollectionResult], PrefectFuture[WriteResult]]
    ] = []
    for company in companies:
        collection_future = collect_company.submit(company, settings.http_timeout_seconds)
        persistence_future = persist_company.submit(
            database_url,
            company.name,
            collection_key,
            captured_at,
            collection_future,
        )
        dispatched.append((company, collection_future, persistence_future))

    logger = get_run_logger()
    successes: list[CompanySuccess] = []
    failures: list[CompanyFailure] = []
    for company, collection_future, persistence_future in dispatched:
        try:
            collection_future.result()
        except Exception as exc:
            persistence_future.wait()
            failure = _company_failure(company.name, "collection", exc)
            failures.append(failure)
            logger.error(
                "Company collection failed: company=%s error_type=%s",
                company.name,
                failure.error_type,
            )
            continue

        try:
            write_result = persistence_future.result()
        except Exception as exc:
            failure = _company_failure(company.name, "persistence", exc)
            failures.append(failure)
            logger.error(
                "Company persistence failed: company=%s error_type=%s",
                company.name,
                failure.error_type,
            )
            continue

        stored = write_result.snapshot
        successes.append(
            CompanySuccess(
                company_name=stored.company_name,
                snapshot_id=stored.snapshot_id,
                source_url=stored.source_url,
                job_count=stored.job_count,
                inserted=write_result.inserted,
            )
        )
        logger.info(
            "Company snapshot persisted: company=%s jobs=%s source_url=%s inserted=%s",
            stored.company_name,
            stored.job_count,
            stored.source_url,
            write_result.inserted,
        )

    status = "completed_with_errors" if failures else "completed"
    summary = FlowSummary(
        status=status,
        flow_run_id=flow_run_id,
        captured_at=captured_at,
        successes=tuple(successes),
        failures=tuple(failures),
    )
    message = (
        f"{len(successes)} company snapshot(s) persisted; "
        f"{len(failures)} company operation(s) failed."
    )
    return Completed(data=summary, message=message)
