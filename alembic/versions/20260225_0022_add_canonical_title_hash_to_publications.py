"""Add canonical_title_hash to publications for cross-scholar dedup.

Revision ID: 20260225_0022
Revises: 20260225_0021
Create Date: 2026-02-25 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260225_0022"
down_revision: str | Sequence[str] | None = "20260225_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "publications",
        sa.Column("canonical_title_hash", sa.String(64), nullable=True),
    )
    op.create_index(
        "ix_publications_canonical_title_hash",
        "publications",
        ["canonical_title_hash"],
    )


def downgrade() -> None:
    op.drop_index("ix_publications_canonical_title_hash", table_name="publications")
    op.drop_column("publications", "canonical_title_hash")
