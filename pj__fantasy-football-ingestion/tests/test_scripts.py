from __future__ import annotations

import runpy

from fantasy_football_ingestion.paths import PROJECT_ROOT


def test_transfer_scripts_import_without_connections() -> None:
    scripts = (
        "publish_table_to_neon.py",
        "publish_draft_picks_to_neon.py",
        "sync_agent_logs_from_neon_to_postgres.py",
    )

    for script in scripts:
        namespace = runpy.run_path(str(PROJECT_ROOT / "scripts" / script), run_name="import_test")
        assert callable(namespace["main"])
