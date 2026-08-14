"""Validated runtime and company configuration."""

from __future__ import annotations

import os
import re
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

import yaml
from prefect.blocks.system import Secret
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PostgresDsn,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Slug = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$"),
]

_DNS_NAME = re.compile(
    r"(?=^.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)


class ConfigurationError(ValueError):
    """Raised when a configuration file cannot be loaded or validated."""


class AppEnvironment(StrEnum):
    """Supported runtime environments."""

    DEV = "dev"
    PROD = "prod"


class LeverRegion(StrEnum):
    """Supported Lever API regions."""

    GLOBAL = "global"
    EU = "eu"


class RuntimeSettings(BaseSettings):
    """Environment-driven settings shared by all application components."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        populate_by_name=True,
        validate_default=True,
    )

    app_env: AppEnvironment = Field(default=AppEnvironment.DEV, validation_alias="APP_ENV")
    database_url: PostgresDsn = Field(validation_alias="DATABASE_URL")
    companies_file: Path = Field(default=Path("companies.yml"), validation_alias="COMPANIES_FILE")
    http_timeout_seconds: float = Field(
        default=30.0,
        gt=0,
        le=300,
        validation_alias="HTTP_TIMEOUT_SECONDS",
    )

    @field_validator("companies_file")
    @classmethod
    def resolve_companies_file(cls, value: Path) -> Path:
        """Resolve relative paths from the process working directory."""
        return value.expanduser().resolve()


class CompanyBase(BaseModel):
    """Fields shared by every supported company source."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: NonEmptyString
    slug: Slug

    @property
    def source_key(self) -> tuple[str, str]:
        """Return the normalized source identity used for duplicate detection."""
        return (self.scraper, self.slug.casefold())


class GreenhouseCompany(CompanyBase):
    """A company hosted on Greenhouse."""

    scraper: Literal["greenhouse"]


class LeverCompany(CompanyBase):
    """A company hosted on Lever."""

    scraper: Literal["lever"]
    region: LeverRegion = LeverRegion.GLOBAL


class EightfoldCompany(CompanyBase):
    """A company hosted on an Eightfold candidate site."""

    scraper: Literal["eightfold"]
    careers_host: NonEmptyString
    domain: NonEmptyString

    @field_validator("careers_host", "domain")
    @classmethod
    def validate_dns_name(cls, value: str) -> str:
        normalized = value.casefold().rstrip(".")
        if not _DNS_NAME.fullmatch(normalized):
            raise ValueError("must be a DNS name without a scheme, port, path, or query")
        return normalized


class GoogleCompany(CompanyBase):
    """Google's first-party careers site."""

    scraper: Literal["google"]

    @model_validator(mode="after")
    def require_google_slug(self) -> GoogleCompany:
        if self.slug.casefold() != "google":
            raise ValueError("the Google Careers adapter requires slug 'google'")
        return self


Company = Annotated[
    GreenhouseCompany | LeverCompany | EightfoldCompany | GoogleCompany,
    Field(discriminator="scraper"),
]


class CompaniesConfig(BaseModel):
    """Validated contents of ``companies.yml``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    companies: list[Company] = Field(min_length=1, max_length=9)

    @model_validator(mode="after")
    def reject_duplicates(self) -> CompaniesConfig:
        names: set[str] = set()
        source_keys: set[tuple[str, str]] = set()

        for company in self.companies:
            normalized_name = company.name.casefold()
            if normalized_name in names:
                raise ValueError(f"duplicate company name: {company.name!r}")
            names.add(normalized_name)

            if company.source_key in source_keys:
                scraper, slug = company.source_key
                raise ValueError(f"duplicate company source: scraper={scraper!r}, slug={slug!r}")
            source_keys.add(company.source_key)

        return self


def load_companies(path: Path | str) -> CompaniesConfig:
    """Load and validate a company configuration file."""
    config_path = Path(path).expanduser().resolve()
    try:
        with config_path.open(encoding="utf-8") as config_file:
            raw_config = yaml.safe_load(config_file)
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"unable to load company configuration: {config_path}") from exc

    try:
        return CompaniesConfig.model_validate(raw_config)
    except ValidationError as exc:
        raise ConfigurationError(f"invalid company configuration: {config_path}\n{exc}") from exc


def load_runtime_settings() -> RuntimeSettings:
    """Load settings, resolving a named Prefect Secret only inside the running process."""
    secret_block_name = os.environ.get("DATABASE_URL_SECRET_BLOCK", "").strip()
    if "DATABASE_URL" not in os.environ and secret_block_name:
        database_url = Secret.load(secret_block_name).get()
        return RuntimeSettings(database_url=database_url)
    return RuntimeSettings()
