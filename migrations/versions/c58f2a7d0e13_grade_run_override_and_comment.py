"""grade_run, grade_override and grade_comment (T8.1, I3.2–I3.5, A12)

A run is immutable, so there is nothing to update: regrading inserts another row. An override is
a separate record with a reason and a partial unique index keeping one current row per component,
which is what lets an instructor's judgement outlive the next run of the engine.

Points are stored in hundredths of a point, for the same reason money is stored in cents.

Revision ID: c58f2a7d0e13
Revises: a71c3d5e9b42
Create Date: 2026-09-17 16:20:00.000000

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'c58f2a7d0e13'
down_revision = 'a71c3d5e9b42'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'grade_run',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('workspace_id', sa.BigInteger(), nullable=False),
        sa.Column('pack_version_id', sa.BigInteger(), nullable=False),
        sa.Column('variant_id', sa.BigInteger(), nullable=False),
        sa.Column('engine_version', sa.String(length=20), nullable=False),
        sa.Column('total_points', sa.BigInteger(), nullable=False),
        sa.Column('max_points', sa.BigInteger(), nullable=False),
        sa.Column('needs_review', sa.Boolean(), nullable=False),
        sa.Column('submission_status', sa.String(length=20), nullable=False),
        sa.Column('results', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_by_id', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                  nullable=False),
        sa.CheckConstraint(
            "submission_status IN ('open', 'submitted', 'submitted_late', 'not_submitted')",
            name='grade_run_submission_status',
        ),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspace.id'], ),
        sa.ForeignKeyConstraint(['created_by_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_grade_run_workspace', 'grade_run', ['workspace_id', 'created_at'])

    op.create_table(
        'grade_override',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('workspace_id', sa.BigInteger(), nullable=False),
        sa.Column('component_key', sa.String(length=40), nullable=False),
        sa.Column('points', sa.BigInteger(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('created_by_id', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                  nullable=False),
        sa.Column('superseded_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspace.id'], ),
        sa.ForeignKeyConstraint(['created_by_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'uq_grade_override_current', 'grade_override', ['workspace_id', 'component_key'],
        unique=True, postgresql_where=sa.text('superseded_at IS NULL'),
    )

    op.create_table(
        'grade_comment',
        sa.Column('workspace_id', sa.BigInteger(), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('updated_by_id', sa.BigInteger(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                  nullable=False),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspace.id'], ),
        sa.ForeignKeyConstraint(['updated_by_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('workspace_id'),
    )


def downgrade():
    op.drop_table('grade_comment')
    op.drop_index('uq_grade_override_current', table_name='grade_override')
    op.drop_table('grade_override')
    op.drop_index('ix_grade_run_workspace', table_name='grade_run')
    op.drop_table('grade_run')
