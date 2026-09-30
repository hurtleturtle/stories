"""relative artifact paths

Revision ID: c5f1a8d20e64
Revises: a4d8c2e71b95
Create Date: 2026-09-30 16:00:00.000000

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

from story_scraper.config import settings


revision: str = 'c5f1a8d20e64'
down_revision: str | None = 'a4d8c2e71b95'
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # Artifact paths used to be recorded absolute, which ties the data to one
    # mount point. Make those under the artifact folder relative to it; new rows
    # are written that way. Rows outside the folder are left alone, and the app
    # still reads absolute paths, so nothing depends on this having matched.
    prefix = settings.story_folder.rstrip("/") + "/"
    op.get_bind().execute(
        sa.text(
            "UPDATE artifacts SET path = substr(path, :start) WHERE left(path, :length) = :prefix"
        ),
        {"start": len(prefix) + 1, "length": len(prefix), "prefix": prefix},
    )


def downgrade() -> None:
    prefix = settings.story_folder.rstrip("/") + "/"
    op.get_bind().execute(
        sa.text("UPDATE artifacts SET path = :prefix || path WHERE left(path, 1) <> '/'"),
        {"prefix": prefix},
    )
