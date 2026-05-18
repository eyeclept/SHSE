"""crawl_jobs: add progress column (0-100 integer)

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-18

"""
from alembic import op
import sqlalchemy as sa

revision = '0013'
down_revision = '0012'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'crawl_jobs',
        sa.Column('progress', sa.Integer(), nullable=True, server_default='0'),
    )


def downgrade():
    op.drop_column('crawl_jobs', 'progress')
