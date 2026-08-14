"""Database persistence for collected snapshots."""

from career_page_snapshots.database.writer import (
    SnapshotRecord,
    WriteResult,
    persist_snapshot,
    write_snapshot,
)

__all__ = ["SnapshotRecord", "WriteResult", "persist_snapshot", "write_snapshot"]
