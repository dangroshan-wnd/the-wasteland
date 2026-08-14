"""Offline production deployment-contract tests."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

import career_page_snapshots.deployment as deployment_module

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _project_yaml() -> dict[str, object]:
    with (PROJECT_ROOT / "prefect.yaml").open(encoding="utf-8") as prefect_file:
        loaded = yaml.safe_load(prefect_file)
    assert isinstance(loaded, dict)
    return loaded


def _write_yaml(tmp_path: Path, contents: dict[str, object]) -> Path:
    metadata_path = tmp_path / "prefect.yaml"
    metadata_path.write_text(yaml.safe_dump(contents, sort_keys=False), encoding="utf-8")
    (tmp_path / "requirements-prod.txt").write_text(".\n", encoding="utf-8")
    return metadata_path


def test_project_deployment_validates_offline() -> None:
    validated = deployment_module.validate_deployment(PROJECT_ROOT / "prefect.yaml")

    assert validated.flow.name == "career-page-snapshots"
    assert validated.deployment.name == "production"
    assert validated.deployment.paused is False
    assert validated.deployment.work_pool.name == "career-page-snapshots-managed"
    assert (
        validated.deployment.work_pool.job_variables["image"]
        == "prefecthq/prefect-client:3-python3.12"
    )
    schedule = validated.deployment.schedules[0]
    assert schedule.cron == "0 21 * * *"
    assert schedule.timezone == "America/New_York"
    assert schedule.active is True
    clone = validated.deployment_file.pull[0]["prefect.deployments.steps.git_clone"]
    assert clone["commit_sha"] == "{{ $GITHUB_SHA }}"
    assert "branch" not in clone
    assert "access_token" not in clone


@pytest.mark.parametrize("forbidden_key", ["image", "storage", "infrastructure"])
def test_validation_rejects_unknown_deployment_fields(forbidden_key: str, tmp_path: Path) -> None:
    contents = deepcopy(_project_yaml())
    deployments = contents["deployments"]
    assert isinstance(deployments, list)
    deployments[0][forbidden_key] = "configured"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        deployment_module.validate_deployment(_write_yaml(tmp_path, contents))


def test_validation_rejects_deactivated_schedule(tmp_path: Path) -> None:
    contents = deepcopy(_project_yaml())
    contents["deployments"][0]["schedules"][0]["active"] = False

    with pytest.raises(ValidationError, match="schedule must remain active"):
        deployment_module.validate_deployment(_write_yaml(tmp_path, contents))


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("DATABASE_URL", "runtime Neon Secret block"),
    ],
)
def test_validation_rejects_literal_secrets(value: str, message: str, tmp_path: Path) -> None:
    contents = deepcopy(_project_yaml())
    env = contents["deployments"][0]["work_pool"]["job_variables"]["env"]
    env[value] = "postgresql://user:password@example.invalid/prod"

    with pytest.raises(ValidationError, match=message):
        deployment_module.validate_deployment(_write_yaml(tmp_path, contents))


def test_validation_rejects_git_credentials(tmp_path: Path) -> None:
    contents = deepcopy(_project_yaml())
    clone = contents["pull"][0]["prefect.deployments.steps.git_clone"]
    clone["access_token"] = "github_pat_literal"

    with pytest.raises(ValidationError, match="public Wasteland URL"):
        deployment_module.validate_deployment(_write_yaml(tmp_path, contents))


def test_production_requirements_install_the_project_without_dev_dependencies() -> None:
    requirements = (PROJECT_ROOT / "requirements-prod.txt").read_text(encoding="utf-8")

    assert requirements.splitlines()[0] == "."
    assert "pytest==" not in requirements
    assert "ruff==" not in requirements
    assert "dbt-postgres==" not in requirements
