"""crawl_jobs table

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-20

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'crawl_jobs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('task_id', sa.String(length=256), nullable=True),
        sa.Column('target_id', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=64), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['target_id'], ['crawler_targets.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('task_id'),
    )


def downgrade():
    op.drop_table('crawl_jobs')
