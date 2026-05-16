"""webauthn_credentials: add table for FIDO2/WebAuthn security key credentials

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-16

"""
from alembic import op
import sqlalchemy as sa

revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'webauthn_credentials',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('credential_id', sa.LargeBinary(255), unique=True, nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('public_key', sa.LargeBinary(1024), nullable=False),
        sa.Column('sign_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('aaguid', sa.String(36), nullable=True),
        sa.Column('name', sa.String(64), nullable=False, server_default='Security Key'),
        sa.Column('registered_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table('webauthn_credentials')
