"""Add shared arXiv runtime state table.

Revision ID: 20260226_0023
Revises: 20260225_0022
Create Date: 2026-02-26 12:40:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260226_0023"
down_revision: str | Sequence[str] | None = "20260225_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    if "arxiv_runtime_state" in table_names:
        return

    op.create_table(
        "arxiv_runtime_state",
        sa.Column("state_key", sa.String(length=64), nullable=False),
        sa.Column("next_allowed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
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
        sa.PrimaryKeyConstraint("state_key", name=op.f("pk_arxiv_runtime_state")),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())
    if "arxiv_runtime_state" in table_names:
        op.drop_table("arxiv_runtime_state")
