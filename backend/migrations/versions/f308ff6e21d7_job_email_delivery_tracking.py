"""job email delivery tracking

Revision ID: f308ff6e21d7
Revises: b9dd3bb530ba
Create Date: 2026-09-15 21:45:03.835331

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'f308ff6e21d7'
down_revision: str | None = 'b9dd3bb530ba'
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

# create_type=False keeps add_column from trying to emit CREATE TYPE itself
# (it does not, which is why the type is created explicitly below).
email_status = postgresql.ENUM(
    'not_sent', 'pending', 'sent', 'failed', name='emailstatus', create_type=False
)


def upgrade() -> None:
    email_status.create(op.get_bind(), checkfirst=True)
    op.add_column(
        'jobs',
        sa.Column('email_status', email_status, server_default='not_sent', nullable=False),
    )
    op.add_column('jobs', sa.Column('email_recipient', sa.String(), nullable=True))
    op.add_column('jobs', sa.Column('email_error', sa.Text(), nullable=True))
    op.add_column('jobs', sa.Column('email_sent_at', sa.DateTime(), nullable=True))

    # Jobs that already emailed a Kindle copy on completion should not come
    # back as "never sent" - their log line is the only record we have.
    op.execute(
        """
        UPDATE jobs
           SET email_status = 'sent'
         WHERE status = 'success'
           AND log LIKE '%Emailed %'
        """
    )


def downgrade() -> None:
    op.drop_column('jobs', 'email_sent_at')
    op.drop_column('jobs', 'email_error')
    op.drop_column('jobs', 'email_recipient')
    op.drop_column('jobs', 'email_status')
    email_status.drop(op.get_bind(), checkfirst=True)
