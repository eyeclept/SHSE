"""crawler_targets: add crawl_depth column

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-26

"""
from alembic import op
import sqlalchemy as sa

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'crawler_targets',
        sa.Column('crawl_depth', sa.Integer(), nullable=True, server_default='2'),
    )


def downgrade():
    op.drop_column('crawler_targets', 'crawl_depth')
