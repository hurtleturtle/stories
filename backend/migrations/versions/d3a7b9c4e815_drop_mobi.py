"""drop mobi

Revision ID: d3a7b9c4e815
Revises: c5f1a8d20e64
Create Date: 2026-09-30 16:20:00.000000

"""
from collections.abc import Sequence

from alembic import op


revision: str = 'd3a7b9c4e815'
down_revision: str | None = 'c5f1a8d20e64'
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # MOBI is no longer a format a job can produce. Anything still configured for
    # it would be rejected: a template would fail when used, and a queued or
    # retried job would fail when it started. Those become EPUB, the default.
    # Finished jobs keep their config (and their .mobi artifacts, which still
    # download) as a record of what was made.
    op.execute("UPDATE templates SET ebook_type = 'epub' WHERE ebook_type = 'mobi'")
    op.execute(
        """
        UPDATE jobs
           SET config = jsonb_set(config, '{ebook_type}', '"epub"')
         WHERE config ->> 'ebook_type' = 'mobi'
           AND status IN ('pending', 'running', 'failed', 'cancelled')
        """
    )


def downgrade() -> None:
    # Which templates and jobs used to say mobi is not recorded, so there is
    # nothing to restore. They stay as epub.
    pass
