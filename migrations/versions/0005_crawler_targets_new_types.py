"""crawler_targets: add new target types and type-specific columns

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-24

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        'crawler_targets',
        'target_type',
        existing_type=sa.Enum('service', 'network'),
        type_=sa.Enum('service', 'network', 'oai-pmh', 'feed', 'api-push'),
        existing_nullable=False,
    )
    op.add_column('crawler_targets', sa.Column('endpoint', sa.String(256), nullable=True))
    op.add_column('crawler_targets', sa.Column('feed_path', sa.String(256), nullable=True))
    op.add_column('crawler_targets', sa.Column('adapter', sa.String(256), nullable=True))


def downgrade():
    op.drop_column('crawler_targets', 'adapter')
    op.drop_column('crawler_targets', 'feed_path')
    op.drop_column('crawler_targets', 'endpoint')
    op.alter_column(
        'crawler_targets',
        'target_type',
        existing_type=sa.Enum('service', 'network', 'oai-pmh', 'feed', 'api-push'),
        type_=sa.Enum('service', 'network'),
        existing_nullable=False,
    )
