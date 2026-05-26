"""add is_encrypted flag

Revision ID: 003
Revises: 002
Create Date: 2026-05-26 12:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column('keys', sa.Column('is_encrypted', sa.Boolean(), server_default='0', nullable=False))

def downgrade() -> None:
    op.drop_column('keys', 'is_encrypted')
