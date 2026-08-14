"""Non-destructive readiness checks for a manual development run."""

from __future__ import annotations

import sys
from dataclasses import dataclass

import psycopg

from career_page_snapshots.config import RuntimeSettings, load_companies, load_runtime_settings


@dataclass(frozen=True, slots=True)
class ReadinessResult:
    """One safe, user-facing readiness check result."""

    name: str
    passed: bool
    detail: str


def check_readiness(settings: RuntimeSettings | None = None) -> tuple[ReadinessResult, ...]:
    """Validate configuration and database objects without changing either."""
    runtime = settings or load_runtime_settings()
    companies = load_companies(runtime.companies_file).companies
    company_names = ", ".join(company.name for company in companies)
    results = [
        ReadinessResult(
            name="company configuration",
            passed=True,
            detail=f"{len(companies)} configured: {company_names}",
        )
    ]

    with psycopg.connect(str(runtime.database_url)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    current_database(),
                    to_regclass('landing.career_page_snapshots'),
                    (SELECT version_num FROM alembic_version LIMIT 1)
                """
            )
            database_name, snapshot_table, revision = cursor.fetchone()

    results.append(
        ReadinessResult(
            name="database connection",
            passed=True,
            detail=f"connected to {database_name}",
        )
    )
    results.append(
        ReadinessResult(
            name="snapshot migration",
            passed=snapshot_table == "landing.career_page_snapshots" and revision is not None,
            detail=(
                f"landing.career_page_snapshots is available at revision {revision}"
                if snapshot_table is not None and revision is not None
                else "run Alembic migrations before ingestion"
            ),
        )
    )
    return tuple(results)


def _safe_error(exc: BaseException) -> str:
    """Return a bounded diagnostic without rendering runtime settings."""
    message = str(exc).strip() or type(exc).__name__
    return message[:500]


def main() -> int:
    """Print readiness checks and return a shell-friendly exit status."""
    try:
        results = check_readiness()
    except Exception as exc:
        print(f"[FAIL] readiness: {_safe_error(exc)}", file=sys.stderr)
        return 1

    for result in results:
        status = "PASS" if result.passed else "FAIL"
        print(f"[{status}] {result.name}: {result.detail}")
    return 0 if all(result.passed for result in results) else 1
