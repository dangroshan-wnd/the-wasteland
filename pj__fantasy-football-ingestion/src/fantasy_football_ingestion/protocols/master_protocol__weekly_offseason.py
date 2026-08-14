# TO RUN: `python -m fantasy_football_ingestion.protocols.master_protocol__weekly_offseason`

import importlib
import sys

# -------------------------
# Protocol Notes
# -------------------------

# Offseason weekly ingest: UD draft pipeline for new picks and entries.
# Toggles (TEST_MODE, slate filters, sleep, etc.) live in each child script.

# -------------------------
# Steps (order matters)
# -------------------------

STEPS = [
    ("fantasy_football_ingestion.jobs.ingest__ud__drafts", "ingest__ud__drafts.py"),
    ("fantasy_football_ingestion.jobs.ingest__ud__draft_entries", "ingest__ud__draft_entries.py"),
    (
        "fantasy_football_ingestion.jobs.ingest__ud__draft_entry_picks",
        "ingest__ud__draft_entry_picks.py",
    ),
]


def run_step(step_index, module_name, script_name):
    print(f"\n{'=' * 60}")
    print(f"Step {step_index}/{len(STEPS)}: {script_name}")
    print("=" * 60)
    module = importlib.import_module(module_name)
    module.main()


def main():
    print("master_protocol__weekly_offseason")
    try:
        for i, (module_name, script_name) in enumerate(STEPS, start=1):
            run_step(i, module_name, script_name)
    except KeyboardInterrupt:
        print("\nProtocol interrupted — later steps were not run.")
        sys.exit(130)

    print(f"\nProtocol complete ({len(STEPS)} steps).")


if __name__ == "__main__":
    main()
