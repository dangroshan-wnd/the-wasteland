"""Prefect flows for career-page collection."""

from career_page_snapshots.flows.ingestion import career_page_snapshots_flow

__all__ = ["career_page_snapshots_flow"]
