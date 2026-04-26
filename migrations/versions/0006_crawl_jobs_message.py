"""crawl_jobs: add message column for error text

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-26

"""
from alembic import op
import sqlalchemy as sa

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('crawl_jobs', sa.Column('message', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('crawl_jobs', 'message')
