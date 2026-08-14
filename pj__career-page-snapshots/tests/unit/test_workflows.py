"""Static safety checks for GitHub Actions workflow boundaries."""

from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = PROJECT_ROOT.parent


def test_deploy_workflow_registers_managed_deployment_safely() -> None:
    workflow_path = REPOSITORY_ROOT / ".github/workflows/career-page-snapshots-deploy.yml"
    contents = workflow_path.read_text(encoding="utf-8")
    workflow = yaml.load(contents, Loader=yaml.BaseLoader)

    triggers = workflow["on"]
    assert triggers["push"]["branches"] == ["main"]
    assert "workflow_dispatch" in triggers
    assert workflow["permissions"] == {"contents": "read"}
    assert "NEON_DATABASE_URL" not in contents
    assert "DATABASE_URL:" not in contents
    assert "docker build" not in contents
    assert "career-page-snapshots-deployment validate" in contents
    assert "prefect deploy --all --no-prompt" in contents
    assert "work-pool create career-page-snapshots-managed --type prefect:managed" in contents
    assert "requirements-prod.generated.txt" in contents
    assert "PREFECT_API_URL" in contents
    assert "PREFECT_API_KEY" in contents
    assert "Manual deployment requested" in contents
    assert "deployment skipped" in contents
    assert "schedule runs daily" in contents
    assert "PREFECT_HOME: /tmp/prefect" in contents
    assert "runner.temp" not in contents
    assert "working-directory: pj__career-page-snapshots" in contents
    assert "pj__career-page-snapshots/prefect.yaml" in contents


def test_ci_workflow_runs_actionlint() -> None:
    contents = (REPOSITORY_ROOT / ".github/workflows/career-page-snapshots-ci.yml").read_text(
        encoding="utf-8"
    )

    assert "docker://rhysd/actionlint:1.7.12" in contents
    assert "working-directory: pj__career-page-snapshots" in contents
    assert "dbt parse" not in contents
    assert "pytest -m integration" in contents
    assert "docker build --tag career-page-snapshots:ci ." in contents
