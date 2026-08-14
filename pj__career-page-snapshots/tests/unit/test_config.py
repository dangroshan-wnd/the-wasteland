import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from career_page_snapshots.config import (
    AppEnvironment,
    CompaniesConfig,
    ConfigurationError,
    EightfoldCompany,
    GoogleCompany,
    GreenhouseCompany,
    LeverCompany,
    LeverRegion,
    RuntimeSettings,
    load_companies,
    load_runtime_settings,
)


def test_loads_definitive_v1_companies() -> None:
    project_root = Path(__file__).resolve().parents[2]

    config = load_companies(project_root / "companies.yml")

    assert [company.name for company in config.companies] == [
        "Netflix",
        "Kalshi",
        "Google",
        "Palantir",
    ]
    assert isinstance(config.companies[0], EightfoldCompany)
    assert isinstance(config.companies[1], GreenhouseCompany)
    assert isinstance(config.companies[2], GoogleCompany)
    assert isinstance(config.companies[3], LeverCompany)
    assert config.companies[3].region is LeverRegion.GLOBAL


def test_rejects_duplicate_normalized_company_names() -> None:
    with pytest.raises(ValidationError, match="duplicate company name"):
        CompaniesConfig.model_validate(
            {
                "companies": [
                    {"name": "Kalshi", "scraper": "greenhouse", "slug": "kalshi"},
                    {"name": " kalshi ", "scraper": "lever", "slug": "kalshi-jobs"},
                ]
            }
        )


def test_rejects_duplicate_normalized_source_keys() -> None:
    with pytest.raises(ValidationError, match="duplicate company source"):
        CompaniesConfig.model_validate(
            {
                "companies": [
                    {"name": "First", "scraper": "lever", "slug": "Board"},
                    {"name": "Second", "scraper": "lever", "slug": "board"},
                ]
            }
        )


@pytest.mark.parametrize("count", [0, 10])
def test_requires_between_one_and_nine_companies(count: int) -> None:
    companies = [
        {"name": f"Company {index}", "scraper": "lever", "slug": f"company-{index}"}
        for index in range(count)
    ]

    with pytest.raises(ValidationError):
        CompaniesConfig.model_validate({"companies": companies})


@pytest.mark.parametrize(
    ("company", "message"),
    [
        (
            {"name": "Netflix", "scraper": "eightfold", "slug": "netflix"},
            "careers_host",
        ),
        (
            {
                "name": "Netflix",
                "scraper": "eightfold",
                "slug": "netflix",
                "careers_host": "https://explore.jobs.netflix.net/path",
                "domain": "netflix.com",
            },
            "must be a DNS name",
        ),
        (
            {"name": "Palantir", "scraper": "lever", "slug": "palantir", "region": "us"},
            "region",
        ),
        (
            {"name": "Alphabet", "scraper": "google", "slug": "alphabet"},
            "requires slug 'google'",
        ),
        (
            {
                "name": "Kalshi",
                "scraper": "greenhouse",
                "slug": "kalshi",
                "region": "global",
            },
            "Extra inputs are not permitted",
        ),
    ],
)
def test_rejects_invalid_source_specific_configuration(
    company: dict[str, str], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        CompaniesConfig.model_validate({"companies": [company]})


def test_load_companies_wraps_yaml_validation_errors(tmp_path: Path) -> None:
    config_path = tmp_path / "companies.yml"
    config_path.write_text("companies: not-a-list\n", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="invalid company configuration"):
        load_companies(config_path)


def test_runtime_settings_are_validated_and_paths_are_resolved(tmp_path: Path) -> None:
    settings = RuntimeSettings(
        app_env="prod",
        database_url="postgresql://user:password@db.example.com:5432/snapshots",
        companies_file=tmp_path / "companies.yml",
        http_timeout_seconds=12.5,
        _env_file=None,
    )

    assert settings.app_env is AppEnvironment.PROD
    assert settings.companies_file == (tmp_path / "companies.yml").resolve()
    assert settings.http_timeout_seconds == 12.5


def test_runtime_settings_load_environment_aliases(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:password@localhost:5432/snapshots")
    monkeypatch.setenv("COMPANIES_FILE", "config/companies.yml")
    monkeypatch.setenv("HTTP_TIMEOUT_SECONDS", "45")

    settings = RuntimeSettings(_env_file=None)

    assert settings.companies_file == (tmp_path / "config" / "companies.yml").resolve()
    assert settings.http_timeout_seconds == 45


def test_runtime_settings_load_database_secret_at_runtime(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    database_url = "postgresql://runtime:secret@db.example.com:5432/snapshots"

    class FakeSecret:
        def get(self) -> str:
            return database_url

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL_SECRET_BLOCK", "neon-database-url")
    monkeypatch.setattr(
        "career_page_snapshots.config.Secret.load",
        lambda name: FakeSecret() if name == "neon-database-url" else None,
    )

    settings = load_runtime_settings()

    assert str(settings.database_url) == database_url
    assert "DATABASE_URL" not in os.environ


def test_runtime_settings_prefer_local_database_url_over_secret_block(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    database_url = "postgresql://local:secret@localhost:5432/snapshots"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("DATABASE_URL_SECRET_BLOCK", "must-not-load")
    monkeypatch.setattr(
        "career_page_snapshots.config.Secret.load",
        lambda _name: pytest.fail("Secret block should not be loaded"),
    )

    settings = load_runtime_settings()

    assert str(settings.database_url) == database_url


@pytest.mark.parametrize("timeout", [0, 301])
def test_runtime_settings_reject_invalid_timeouts(timeout: int) -> None:
    with pytest.raises(ValidationError):
        RuntimeSettings(
            database_url="postgresql://user:password@localhost:5432/snapshots",
            http_timeout_seconds=timeout,
            _env_file=None,
        )
