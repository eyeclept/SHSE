"""users_totp: add TOTP columns to users table

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-16

"""
from alembic import op
import sqlalchemy as sa

revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('totp_secret', sa.String(64), nullable=True))
    op.add_column('users', sa.Column('totp_enabled', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column('users', 'totp_enabled')
    op.drop_column('users', 'totp_secret')
