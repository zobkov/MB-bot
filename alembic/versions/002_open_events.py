"""open events: conf_events, conf_event_registrations

Revision ID: 002_open_events
Revises: 001_initial
Create Date: 2026-10-15 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '002_open_events'
down_revision: Union[str, None] = '001_initial'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'conf_events',
        sa.Column('code', sa.String(length=50), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('schedule', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('capacity', sa.Integer(), nullable=False),
        sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False),
        sa.PrimaryKeyConstraint('code'),
    )

    op.create_table(
        'conf_event_registrations',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('event_code', sa.String(length=50), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['event_code'], ['conf_events.code']),
        sa.ForeignKeyConstraint(['user_id'], ['conf_users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'event_code', name='uq_conf_event_registrations_user_event'),
    )
    op.create_index(op.f('ix_conf_event_registrations_event_code'), 'conf_event_registrations', ['event_code'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_conf_event_registrations_event_code'), table_name='conf_event_registrations')
    op.drop_table('conf_event_registrations')
    op.drop_table('conf_events')
