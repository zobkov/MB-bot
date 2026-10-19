"""parallel events: conf_parallel_events, conf_parallel_registrations

Revision ID: 003_parallel_events
Revises: 002_open_events
Create Date: 2026-10-19 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '003_parallel_events'
down_revision: Union[str, None] = '002_open_events'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Бот вызывает create_tables() на старте, поэтому таблицы могли появиться раньше миграции —
    # уже существующие пропускаем (схема та же: create_all строит их по тем же моделям)
    existing = set(sa.inspect(op.get_bind()).get_table_names())

    if 'conf_parallel_events' not in existing:
        op.create_table(
            'conf_parallel_events',
            sa.Column('code', sa.String(length=50), nullable=False),
            sa.Column('slot_code', sa.String(length=50), nullable=False),
            sa.Column('title', sa.String(length=255), nullable=False),
            sa.Column('capacity', sa.Integer(), nullable=False),
            sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False),
            sa.PrimaryKeyConstraint('code'),
        )

    if 'conf_parallel_registrations' not in existing:
        op.create_table(
            'conf_parallel_registrations',
            sa.Column('id', sa.BigInteger(), nullable=False),
            sa.Column('user_id', sa.BigInteger(), nullable=False),
            sa.Column('slot_code', sa.String(length=50), nullable=False),
            sa.Column('event_code', sa.String(length=50), nullable=False),
            sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
            sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
            sa.ForeignKeyConstraint(['event_code'], ['conf_parallel_events.code']),
            sa.ForeignKeyConstraint(['user_id'], ['conf_users.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('user_id', 'slot_code', name='uq_conf_parallel_registrations_user_slot'),
        )
        op.create_index(
            op.f('ix_conf_parallel_registrations_event_code'), 'conf_parallel_registrations', ['event_code'], unique=False
        )


def downgrade() -> None:
    op.drop_index(op.f('ix_conf_parallel_registrations_event_code'), table_name='conf_parallel_registrations')
    op.drop_table('conf_parallel_registrations')
    op.drop_table('conf_parallel_events')
