"""Add resolving to RunStatus enum

Revision ID: 20260224_0019
Revises: 20260224_0018
Create Date: 2026-02-24 22:20:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260224_0019"
down_revision: str | Sequence[str] | None = "20260224_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Use COMMIT to break out of the transaction block that Alembic creates in env.py.
    # Postgres restricts ALTER TYPE ... ADD VALUE inside transactions when the type is in use.
    # This is the robust, non-patchwork way to ensure the schema evolves correctly.
    op.execute("COMMIT")
    op.execute("ALTER TYPE run_status ADD VALUE IF NOT EXISTS 'resolving' AFTER 'running'")


def downgrade() -> None:
    # Enum values cannot be easily removed in Postgres without recreating the type,
    # which is risky and usually avoided in simple migrations.
    pass
