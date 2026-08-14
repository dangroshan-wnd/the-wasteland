# TO RUN: `python -m fantasy_football_ingestion.protocols.master_protocol__annual`

import importlib
import sys

# -------------------------
# Protocol Notes
# -------------------------

# Annual ingest: UD reference data, then PFR reference data.
# Toggles (TEST_MODE, slate filters, sleep, etc.) live in each child script.

# -------------------------
# Steps (order matters — UD before PFR)
# -------------------------

STEPS = [
    ("fantasy_football_ingestion.jobs.ingest__ud__teams", "ingest__ud__teams.py"),
    ("fantasy_football_ingestion.jobs.ingest__ud__slates", "ingest__ud__slates.py"),
    ("fantasy_football_ingestion.jobs.ingest__ud__players", "ingest__ud__players.py"),
    ("fantasy_football_ingestion.jobs.ingest__ud__appearances", "ingest__ud__appearances.py"),
    ("fantasy_football_ingestion.jobs.ingest__pfr__active_teams", "ingest__pfr__active_teams.py"),
    (
        "fantasy_football_ingestion.jobs.ingest__pfr__completed_season_schedules",
        "ingest__pfr__completed_season_schedules.py",
    ),
    ("fantasy_football_ingestion.jobs.ingest__pfr__players", "ingest__pfr__players.py"),
]


def run_step(step_index, module_name, script_name):
    print(f"\n{'=' * 60}")
    print(f"Step {step_index}/{len(STEPS)}: {script_name}")
    print("=" * 60)
    module = importlib.import_module(module_name)
    module.main()


def main():
    print("master_protocol__annual")
    try:
        for i, (module_name, script_name) in enumerate(STEPS, start=1):
            run_step(i, module_name, script_name)
    except KeyboardInterrupt:
        print("\nProtocol interrupted — later steps were not run.")
        sys.exit(130)

    print(f"\nProtocol complete ({len(STEPS)} steps).")


if __name__ == "__main__":
    main()
