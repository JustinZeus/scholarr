"""Add openalex_last_attempt_at to publications

Revision ID: 20260224_0020
Revises: 20260224_0019
Create Date: 2026-02-24 22:50:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260224_0020"
down_revision: str | Sequence[str] | None = "20260224_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("publications", sa.Column("openalex_last_attempt_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("publications", "openalex_last_attempt_at")
