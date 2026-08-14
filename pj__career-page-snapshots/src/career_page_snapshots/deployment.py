"""Offline validation for the production Prefect deployment contract."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Annotated, Any

import prefect
import yaml
from prefect.flows import Flow, load_flow_from_entrypoint
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

_GITHUB_REPOSITORY = "https://github.com/dangroshan-wnd/the-wasteland.git"
_GITHUB_SHA = "{{ $GITHUB_SHA }}"
_PROJECT_DIRECTORY = "{{ clone-repository.directory }}/pj__career-page-snapshots"


class ScheduleConfig(BaseModel):
    """The daily production schedule."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cron: NonEmptyString
    timezone: NonEmptyString
    slug: NonEmptyString
    active: bool


class ConcurrencyConfig(BaseModel):
    """Deployment concurrency policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    limit: int = Field(ge=1)
    collision_strategy: NonEmptyString


class WorkPoolConfig(BaseModel):
    """Prefect Managed work-pool selection and runtime environment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: NonEmptyString
    work_queue_name: NonEmptyString
    job_variables: dict[str, Any]


class DeploymentConfig(BaseModel):
    """Runnable production deployment fields supported by this project."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: NonEmptyString
    version: NonEmptyString
    description: NonEmptyString
    entrypoint: NonEmptyString
    parameters: dict[str, object] = Field(default_factory=dict)
    tags: tuple[NonEmptyString, ...] = ()
    paused: bool
    concurrency_limit: ConcurrencyConfig
    schedules: tuple[ScheduleConfig, ...] = Field(min_length=1, max_length=1)
    work_pool: WorkPoolConfig


class PrefectDeploymentFile(BaseModel):
    """Strict, version-controlled subset of ``prefect.yaml``."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    name: NonEmptyString
    prefect_version: NonEmptyString = Field(alias="prefect-version")
    build: None
    push: None
    pull: tuple[dict[str, dict[str, object]], ...] = Field(min_length=3, max_length=3)
    deployments: tuple[DeploymentConfig, ...] = Field(min_length=1, max_length=1)

    @model_validator(mode="after")
    def enforce_production_contract(self) -> PrefectDeploymentFile:
        """Reject drift that could make production unsafe or non-reproducible."""
        clone, install, working_directory = self.pull
        expected_clone = {
            "prefect.deployments.steps.git_clone": {
                "id": "clone-repository",
                "repository": _GITHUB_REPOSITORY,
                "commit_sha": _GITHUB_SHA,
            }
        }
        expected_install = {
            "prefect.deployments.steps.pip_install_requirements": {
                "directory": _PROJECT_DIRECTORY,
                "requirements_file": "requirements-prod.txt",
            }
        }
        expected_working_directory = {
            "prefect.deployments.steps.set_working_directory": {"directory": _PROJECT_DIRECTORY}
        }
        if clone != expected_clone:
            raise ValueError("git clone step must use only the public Wasteland URL and GITHUB_SHA")
        if install != expected_install:
            raise ValueError("dependency step must install requirements-prod.txt from the clone")
        if working_directory != expected_working_directory:
            raise ValueError("working directory step must select the snapshotter subdirectory")

        deployment = self.deployments[0]
        if deployment.name != "production" or deployment.version != _GITHUB_SHA:
            raise ValueError("production deployment name and GITHUB_SHA version are required")
        if deployment.paused:
            raise ValueError("production deployment must allow scheduled and manual runs")
        if deployment.concurrency_limit.limit != 1:
            raise ValueError("production concurrency limit must be one")
        if deployment.concurrency_limit.collision_strategy != "ENQUEUE":
            raise ValueError("overlapping runs must be enqueued")

        schedule = deployment.schedules[0]
        if (schedule.cron, schedule.timezone, schedule.slug) != (
            "0 21 * * *",
            "America/New_York",
            "daily-9pm-eastern",
        ):
            raise ValueError("production schedule must be daily at 9 PM America/New_York")
        if not schedule.active:
            raise ValueError("production schedule must remain active after smoke-test acceptance")

        if deployment.work_pool.name != "career-page-snapshots-managed":
            raise ValueError("production must use the Prefect Managed work pool")
        if deployment.work_pool.work_queue_name != "default":
            raise ValueError("production must use the default work queue")
        expected_env = {
            "APP_ENV": "prod",
            "COMPANIES_FILE": "companies.yml",
            "HTTP_TIMEOUT_SECONDS": "30",
            "DATABASE_URL_SECRET_BLOCK": "neon-database-url",
        }
        expected_job_variables = {
            "image": "prefecthq/prefect-client:3-python3.12",
            "env": expected_env,
        }
        if deployment.work_pool.job_variables != expected_job_variables:
            raise ValueError("production job variables must name the runtime Neon Secret block")
        return self


class ValidatedDeployment(BaseModel):
    """Validated deployment configuration plus its imported Prefect flow."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    deployment_file: PrefectDeploymentFile
    deployment: DeploymentConfig
    flow: Flow[..., object]


def validate_deployment(path: Path | str = Path("prefect.yaml")) -> ValidatedDeployment:
    """Validate YAML invariants and import the flow without contacting Prefect Cloud."""
    deployment_path = Path(path).expanduser().resolve()
    with deployment_path.open(encoding="utf-8") as deployment_file:
        raw = yaml.safe_load(deployment_file)
    parsed = PrefectDeploymentFile.model_validate(raw)
    if parsed.prefect_version != prefect.__version__:
        raise ValueError(
            f"prefect.yaml requires Prefect {parsed.prefect_version}, "
            f"but {prefect.__version__} is installed"
        )

    deployment = parsed.deployments[0]
    entrypoint_path, separator, object_name = deployment.entrypoint.rpartition(":")
    if not separator or not entrypoint_path or not object_name:
        raise ValueError("deployment entrypoint must use 'path.py:flow_object' syntax")
    resolved_entrypoint = deployment_path.parent / entrypoint_path
    if not resolved_entrypoint.is_file():
        raise ValueError(f"deployment entrypoint file does not exist: {entrypoint_path}")

    requirements_path = deployment_path.parent / "requirements-prod.txt"
    if not requirements_path.is_file():
        raise ValueError("requirements-prod.txt does not exist")

    flow = load_flow_from_entrypoint(f"{resolved_entrypoint}:{object_name}")
    return ValidatedDeployment(
        deployment_file=parsed,
        deployment=deployment,
        flow=flow,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate the Prefect production deployment.")
    parser.add_argument("command", choices=("validate",), help="validate entirely offline")
    parser.add_argument("--file", type=Path, default=Path("prefect.yaml"))
    return parser


def main() -> int:
    """Run deployment validation."""
    args = _parser().parse_args()
    validated = validate_deployment(args.file)
    schedule = validated.deployment.schedules[0]
    print(
        f"Validated {validated.flow.name!r} deployment {validated.deployment.name!r}: "
        f"{schedule.cron} {schedule.timezone} (schedule active)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
