"""assignment_override: one student's own deadline (I1.11)

Extended time is not a favour; for some students it is the difference between being able to sit
the assignment and not. A partial unique index keeps one live accommodation per student per
assignment, and withdrawing one leaves the record of it behind.

Revision ID: b3d81f0c25aa
Revises: 458010afcab4
Create Date: 2026-09-19 02:10:00.000000

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'b3d81f0c25aa'
down_revision = '458010afcab4'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'assignment_override',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('assignment_id', sa.BigInteger(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('due_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('late_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('checkpoint_extension_hours', sa.Integer(), nullable=True),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('created_by_id', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                  nullable=False),
        sa.Column('withdrawn_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['assignment_id'], ['assignment.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
        sa.ForeignKeyConstraint(['created_by_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'uq_assignment_override_current', 'assignment_override', ['assignment_id', 'user_id'],
        unique=True, postgresql_where=sa.text('withdrawn_at IS NULL'),
    )


def downgrade():
    op.drop_index('uq_assignment_override_current', table_name='assignment_override')
    op.drop_table('assignment_override')
