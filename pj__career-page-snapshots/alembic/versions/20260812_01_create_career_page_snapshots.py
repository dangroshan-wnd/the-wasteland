"""Create the landing career-page snapshot table.

Revision ID: 20260812_01
Revises:
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260812_01"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "landing"
TABLE = "career_page_snapshots"


def upgrade() -> None:
    """Create the owned table and its constraints without claiming the schema."""
    op.execute(sa.schema.CreateSchema(SCHEMA, if_not_exists=True))
    op.create_table(
        TABLE,
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_name", sa.Text(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("job_count", sa.Integer(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("collection_key", sa.Text(), nullable=False),
        sa.CheckConstraint("job_count >= 0", name="ck_career_page_snapshots_job_count"),
        sa.PrimaryKeyConstraint("snapshot_id", name="pk_career_page_snapshots"),
        sa.UniqueConstraint(
            "company_name",
            "collection_key",
            name="uq_career_page_snapshots_company_collection",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_career_page_snapshots_company_captured_at",
        TABLE,
        ["company_name", sa.text("captured_at DESC")],
        unique=False,
        schema=SCHEMA,
    )
    op.create_index(
        "ix_career_page_snapshots_captured_at",
        TABLE,
        [sa.text("captured_at DESC")],
        unique=False,
        schema=SCHEMA,
    )


def downgrade() -> None:
    """Remove only this migration's objects and preserve the shared schema."""
    op.drop_index(
        "ix_career_page_snapshots_captured_at",
        table_name=TABLE,
        schema=SCHEMA,
    )
    op.drop_index(
        "ix_career_page_snapshots_company_captured_at",
        table_name=TABLE,
        schema=SCHEMA,
    )
    op.drop_table(TABLE, schema=SCHEMA)
    # The migration cannot know whether `landing` predated this project. Leaving
    # an empty schema is safer than deleting a schema another workload may own.
