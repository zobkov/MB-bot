"""initial: conf_users, conf_debate_companies, conf_debate_registrations, conf_settings

Revision ID: 001_initial
Revises:
Create Date: 2026-10-12 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '001_initial'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'conf_users',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('telegram_id', sa.BigInteger(), nullable=False),
        sa.Column('telegram_username', sa.String(length=255), nullable=True),
        sa.Column('role', sa.String(length=20), server_default='guest', nullable=False),
        sa.Column('role_overridden', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_conf_users_telegram_id'), 'conf_users', ['telegram_id'], unique=True)

    op.create_table(
        'conf_debate_companies',
        sa.Column('code', sa.String(length=50), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('capacity', sa.Integer(), nullable=False),
        sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False),
        sa.PrimaryKeyConstraint('code'),
    )

    op.create_table(
        'conf_debate_registrations',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('company_code', sa.String(length=50), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['company_code'], ['conf_debate_companies.code']),
        sa.ForeignKeyConstraint(['user_id'], ['conf_users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id'),
    )
    op.create_index(op.f('ix_conf_debate_registrations_company_code'), 'conf_debate_registrations', ['company_code'], unique=False)

    op.create_table(
        'conf_settings',
        sa.Column('key', sa.String(length=100), nullable=False),
        sa.Column('value', sa.String(length=255), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('key'),
    )


def downgrade() -> None:
    op.drop_table('conf_settings')
    op.drop_index(op.f('ix_conf_debate_registrations_company_code'), table_name='conf_debate_registrations')
    op.drop_table('conf_debate_registrations')
    op.drop_table('conf_debate_companies')
    op.drop_index(op.f('ix_conf_users_telegram_id'), table_name='conf_users')
    op.drop_table('conf_users')
