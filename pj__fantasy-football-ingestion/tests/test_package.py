from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

import fantasy_football_ingestion
from fantasy_football_ingestion.paths import (
    PFR_TEAM_ABBREVIATION_MAP_PATH,
    PROJECT_ROOT,
    SAMPLES_DIR,
)


def test_all_package_modules_import_without_external_calls() -> None:
    discovered = {
        module.name
        for module in pkgutil.walk_packages(
            fantasy_football_ingestion.__path__,
            prefix=f"{fantasy_football_ingestion.__name__}.",
        )
    }

    for module_name in sorted(discovered):
        importlib.import_module(module_name)

    assert "fantasy_football_ingestion.jobs.ingest__ud__drafts" in discovered
    assert "fantasy_football_ingestion.scrapers.pro_football_reference" in discovered


def test_paths_resolve_inside_this_subproject() -> None:
    assert PROJECT_ROOT.name == "pj__fantasy-football-ingestion"
    assert (
        PROJECT_ROOT / "src" / "fantasy_football_ingestion"
        == Path(fantasy_football_ingestion.__file__).parent
    )
    assert SAMPLES_DIR.is_dir()
    assert len(list(SAMPLES_DIR.glob("sample__*.json"))) == 10
    assert PFR_TEAM_ABBREVIATION_MAP_PATH.is_file()
    assert '"Washington Commanders": "was"' in PFR_TEAM_ABBREVIATION_MAP_PATH.read_text(
        encoding="utf-8"
    )


def test_source_has_no_fantasy_repository_path_hacks() -> None:
    source_root = PROJECT_ROOT / "src"
    source = "\n".join(path.read_text(encoding="utf-8") for path in source_root.rglob("*.py"))

    assert "sys.path" not in source
    assert "from connect import" not in source
    assert "from python.scrapers" not in source
    assert 'PROJECT_ROOT / "dbt" / "seeds"' not in source
