"""job heartbeat

Revision ID: a4d8c2e71b95
Revises: 3c7a1e9d2b40
Create Date: 2026-09-30 15:10:00.000000

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'a4d8c2e71b95'
down_revision: str | None = '3c7a1e9d2b40'
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # Nullable on purpose: jobs already running when this is applied have no
    # heartbeat, and the stale-job sweep falls back to started_at for them.
    op.add_column('jobs', sa.Column('heartbeat_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('jobs', 'heartbeat_at')
