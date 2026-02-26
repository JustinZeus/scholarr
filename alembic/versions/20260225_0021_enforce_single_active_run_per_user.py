"""Enforce one active crawl run per user.

Revision ID: 20260225_0021
Revises: 20260224_0020
Create Date: 2026-02-25 09:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260225_0021"
down_revision: str | Sequence[str] | None = "20260224_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX_NAME = "uq_crawl_runs_user_active"
ACTIVE_STATUSES = ("running", "resolving")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    indexes = {index["name"] for index in inspector.get_indexes("crawl_runs")}

    op.execute("ALTER TYPE run_status ADD VALUE IF NOT EXISTS 'canceled'")

    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    PARTITION BY user_id
                    ORDER BY start_dt DESC, id DESC
                ) AS rn
            FROM crawl_runs
            WHERE status IN ('running', 'resolving')
        )
        UPDATE crawl_runs AS runs
        SET
            status = 'failed',
            end_dt = COALESCE(runs.end_dt, NOW())
        FROM ranked
        WHERE runs.id = ranked.id
          AND ranked.rn > 1
        """
    )

    if INDEX_NAME not in indexes:
        op.create_index(
            INDEX_NAME,
            "crawl_runs",
            ["user_id"],
            unique=True,
            postgresql_where=sa.text("status IN ('running'::run_status, 'resolving'::run_status)"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    indexes = {index["name"] for index in inspector.get_indexes("crawl_runs")}
    if INDEX_NAME in indexes:
        op.drop_index(INDEX_NAME, table_name="crawl_runs")
