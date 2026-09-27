"""user roles and app settings

Revision ID: 3c7a1e9d2b40
Revises: f308ff6e21d7
Create Date: 2026-09-27 12:00:00.000000

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '3c7a1e9d2b40'
down_revision: str | None = 'f308ff6e21d7'
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

# create_type=False for the same reason as emailstatus: add_column will not
# emit CREATE TYPE, so it is created explicitly below.
user_role = postgresql.ENUM('user', 'admin', name='userrole', create_type=False)


def upgrade() -> None:
    user_role.create(op.get_bind(), checkfirst=True)
    op.add_column(
        'users', sa.Column('role', user_role, server_default='user', nullable=False)
    )

    op.create_table(
        'app_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('allow_registration', sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    # An existing install would otherwise have no admin at all - and with
    # registration closed, no way to get one. The first user to sign up is
    # the admin for new installs, so do the same here.
    op.execute(
        """
        UPDATE users
           SET role = 'admin'
         WHERE id = (SELECT id FROM users ORDER BY created_at, id LIMIT 1)
        """
    )


def downgrade() -> None:
    op.drop_table('app_settings')
    op.drop_column('users', 'role')
    user_role.drop(op.get_bind(), checkfirst=True)
