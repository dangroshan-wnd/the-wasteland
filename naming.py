"""Resolve database.schema names from a pj__* folder using naming.yml."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

NAMING_FILE = "naming.yml"
WASTELAND_ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class ProjectNames:
    folder: str
    project: str
    database: str
    local_database: str
    schema: str

    @property
    def qualified(self) -> str:
        return f"{self.database}.{self.schema}"

    def table(self, name: str) -> str:
        return f"{self.schema}.{name}"


def load_convention(root: Path | None = None) -> dict[str, str]:
    path = (root or WASTELAND_ROOT) / NAMING_FILE
    if not path.is_file():
        raise FileNotFoundError(f"missing naming convention: {path}")

    data: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip().strip("\"'")
    return data


def project_slug(folder: str, prefix: str = "pj__") -> str:
    name = Path(folder).name
    if name.startswith(prefix):
        name = name[len(prefix) :]
    return name.replace("-", "_")


def names_for(folder: str, root: Path | None = None) -> ProjectNames:
    convention = load_convention(root)
    prefix = convention.get("folder_prefix", "pj__")
    project = project_slug(folder, prefix)
    database = convention.get("database", "{project}").replace("{project}", project)
    local_database = convention.get("local_database", "{project}_dev").replace(
        "{project}", project
    )
    schema = convention.get("default_schema", "landing")
    return ProjectNames(
        folder=Path(folder).name,
        project=project,
        database=database,
        local_database=local_database,
        schema=schema,
    )
