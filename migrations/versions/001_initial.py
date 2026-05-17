"""initial

Revision ID: 001
Revises: 
Create Date: 2026-05-18 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '001'
down_revision = None
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Создаем таблицу users
    op.create_table('users',
        sa.Column('tg_id', sa.Integer(), nullable=False),
        sa.Column('username', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('tg_id')
    )
    
    # Создаем таблицу keys
    op.create_table('keys',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('tg_id', sa.Integer(), nullable=True),
        sa.Column('vless_key', sa.Text(), nullable=True),
        sa.Column('price', sa.Integer(), nullable=True),
        sa.Column('next_payment_date', sa.Date(), nullable=True),
        sa.Column('uuid', sa.Text(), nullable=True),
        sa.Column('panel_host', sa.Text(), nullable=True),
        sa.Column('inbound_id', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='1', nullable=True),
        sa.Column('settings', sa.Text(), nullable=True),
        sa.Column('deactivated_at', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['tg_id'], ['users.tg_id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Создаем индексы
    op.create_index('idx_keys_tg_id', 'keys', ['tg_id'], unique=False)
    op.create_index('idx_keys_is_active', 'keys', ['is_active'], unique=False)

def downgrade() -> None:
    op.drop_index('idx_keys_is_active', table_name='keys')
    op.drop_index('idx_keys_tg_id', table_name='keys')
    op.drop_table('keys')
    op.drop_table('users')