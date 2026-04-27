"""crawl_jobs: add kind column to distinguish crawl vs vectorize jobs

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-26

"""
from alembic import op
import sqlalchemy as sa

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'crawl_jobs',
        sa.Column('kind', sa.String(32), nullable=True, server_default='crawl'),
    )


def downgrade():
    op.drop_column('crawl_jobs', 'kind')
