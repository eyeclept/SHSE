"""crawler_targets table

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-20

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'crawler_targets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('nickname', sa.String(length=128), nullable=True),
        sa.Column('target_type', sa.Enum('service', 'network'), nullable=False),
        sa.Column('url', sa.String(length=512), nullable=True),
        sa.Column('ip', sa.String(length=64), nullable=True),
        sa.Column('network', sa.String(length=64), nullable=True),
        sa.Column('port', sa.Integer(), nullable=True),
        sa.Column('route', sa.String(length=256), nullable=True),
        sa.Column('service', sa.String(length=32), nullable=True),
        sa.Column('tls_verify', sa.Boolean(), nullable=True),
        sa.Column('schedule_yaml', sa.Text(), nullable=True),
        sa.Column('yaml_source', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade():
    op.drop_table('crawler_targets')
