"""hardening: add is_suspended and last_notification_sent

Revision ID: 004
Revises: 003
Create Date: 2026-05-26 13:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = '004'
down_revision = '003'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # 0 - активен, 1 - приостановлен за неуплату
    op.add_column('keys', sa.Column('is_suspended', sa.Boolean(), server_default='0', nullable=False))
    # Дата в формате YYYY-MM-DD
    op.add_column('keys', sa.Column('last_notification_sent', sa.Text(), nullable=True))

def downgrade() -> None:
    op.drop_column('keys', 'last_notification_sent')
    op.drop_column('keys', 'is_suspended')
