"""Add arXiv query cache table.

Revision ID: 20260226_0024
Revises: 20260226_0023
Create Date: 2026-02-26 14:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260226_0024"
down_revision: str | Sequence[str] | None = "20260226_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())
    if "arxiv_query_cache_entries" in table_names:
        return

    op.create_table(
        "arxiv_query_cache_entries",
        sa.Column("query_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "cached_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint(
            "query_fingerprint",
            name=op.f("pk_arxiv_query_cache_entries"),
        ),
    )
    op.create_index(
        "ix_arxiv_query_cache_expires_at",
        "arxiv_query_cache_entries",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_arxiv_query_cache_cached_at",
        "arxiv_query_cache_entries",
        ["cached_at"],
        unique=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())
    if "arxiv_query_cache_entries" in table_names:
        op.drop_table("arxiv_query_cache_entries")
