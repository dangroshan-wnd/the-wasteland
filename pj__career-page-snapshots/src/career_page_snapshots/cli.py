"""Local command-line entry point for an unscheduled ingestion run."""

from __future__ import annotations

from career_page_snapshots.flows import career_page_snapshots_flow


def main() -> int:
    """Run the configured flow and print its structured summary."""
    summary = career_page_snapshots_flow()
    print(summary.model_dump_json(indent=2))
    return 0
