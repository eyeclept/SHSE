"""system_settings: add key-value store for admin-configurable runtime settings

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-04

"""
from alembic import op
import sqlalchemy as sa

revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'system_settings',
        sa.Column('key', sa.String(128), primary_key=True),
        sa.Column('value', sa.Text(), nullable=True),
    )


def downgrade():
    op.drop_table('system_settings')
