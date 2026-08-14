from __future__ import annotations

import importlib

from fantasy_football_ingestion.protocols import (
    master_protocol__annual,
    master_protocol__weekly_inseason,
    master_protocol__weekly_offseason,
)


def test_protocol_steps_resolve_to_package_jobs() -> None:
    protocols = (
        master_protocol__annual,
        master_protocol__weekly_inseason,
        master_protocol__weekly_offseason,
    )

    for protocol in protocols:
        assert protocol.STEPS
        for module_name, script_name in protocol.STEPS:
            assert module_name.startswith("fantasy_football_ingestion.jobs.ingest__")
            assert script_name.endswith(".py")
            assert callable(importlib.import_module(module_name).main)
