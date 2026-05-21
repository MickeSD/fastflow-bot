"""add_hash

Revision ID: 002
Revises: 001
Create Date: 2026-05-19 12:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # 1. Добавляем колонку uuid_hash
    op.add_column('keys', sa.Column('uuid_hash', sa.Text(), nullable=True))

    # 2. Создаем частичный уникальный индекс (только для активных ключей)
    # Это та самая магия, которая предотвратит Race Condition
    op.create_index(
        'idx_keys_active_uuid_hash_panel',
        'keys',
        ['panel_host', 'uuid_hash'],
        unique=True,
        sqlite_where=sa.text("is_active = 1")
    )

def downgrade() -> None:
    op.drop_index('idx_keys_active_uuid_hash_panel', table_name='keys')
    op.drop_column('keys', 'uuid_hash')
