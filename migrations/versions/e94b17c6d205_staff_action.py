"""staff_action (D2)

The audit trail for what staff did and why: reopening a workspace, overriding a mark, releasing a
section. The reason is the one given at the time, and the detail holds ids and counts only.

Revision ID: e94b17c6d205
Revises: c58f2a7d0e13
Create Date: 2026-09-17 17:10:00.000000

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'e94b17c6d205'
down_revision = 'c58f2a7d0e13'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'staff_action',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('actor_id', sa.BigInteger(), nullable=True),
        sa.Column('action', sa.String(length=40), nullable=False),
        sa.Column('target_table', sa.String(length=40), nullable=False),
        sa.Column('target_id', sa.BigInteger(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                  nullable=False),
        sa.ForeignKeyConstraint(['actor_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_staff_action_target', 'staff_action',
                    ['target_table', 'target_id', 'created_at'])


def downgrade():
    op.drop_index('ix_staff_action_target', table_name='staff_action')
    op.drop_table('staff_action')
