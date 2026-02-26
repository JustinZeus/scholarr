"""remove_doi_from_publications_and_migrate_identifiers

Revision ID: 44f7e10ef777
Revises: 20260222_0016
Create Date: 2026-02-22 17:03:56.261936

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '44f7e10ef777'
down_revision: str | Sequence[str] | None = '20260222_0016'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

