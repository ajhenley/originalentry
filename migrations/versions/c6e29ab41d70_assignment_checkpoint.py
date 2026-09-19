"""assignment_checkpoint: deadlines and stage gating (I1.2, S6.3)

Keyed by the checkpoint's ordinal rather than its key, so one assignment's rules still make sense
where students may be working on different companies.

Revision ID: c6e29ab41d70
Revises: b3d81f0c25aa
Create Date: 2026-09-19 03:20:00.000000

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'c6e29ab41d70'
down_revision = 'b3d81f0c25aa'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'assignment_checkpoint',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('assignment_id', sa.BigInteger(), nullable=False),
        sa.Column('ordinal', sa.Integer(), nullable=False),
        sa.Column('deadline_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('gates_stage', sa.String(length=20), nullable=True),
        sa.CheckConstraint(
            "gates_stage IS NULL OR gates_stage IN ('adjusting', 'statements', 'closing')",
            name='assignment_checkpoint_stage',
        ),
        sa.ForeignKeyConstraint(['assignment_id'], ['assignment.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('assignment_id', 'ordinal'),
    )


def downgrade():
    op.drop_table('assignment_checkpoint')
