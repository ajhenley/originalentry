"""content_pack.kind and chapter metadata, assignment.problems_required, problem_attempt

The shape a chapter problem set needs. See originalentry/models/content.py,
originalentry/models/work.py and
docs/superpowers/specs/2026-10-20-short-chapter-problems-design.md.

``kind`` is backfilled to 'practice_set' before it is made NOT NULL: every pack that exists today
is a practice set, and a problem set is the new thing. The server default keeps that true for any
code path that inserts a pack without naming a kind -- which is every existing importer.

Revision ID: a6b23d41c8f7
Revises: c3e71f0a95b4
Create Date: 2026-10-20

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'a6b23d41c8f7'
down_revision = 'c3e71f0a95b4'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('content_pack', schema=None) as batch_op:
        batch_op.add_column(sa.Column('kind', sa.String(length=20), nullable=True,
                                      server_default='practice_set'))
        batch_op.add_column(sa.Column('textbook', sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column('chapter_label', sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column('chapter_ordinal', sa.Integer(), nullable=True))

    # Every pack that exists is a practice set. Done before the NOT NULL so the column can never
    # be briefly null for a row somebody reads.
    op.execute("UPDATE content_pack SET kind = 'practice_set' WHERE kind IS NULL")

    with op.batch_alter_table('content_pack', schema=None) as batch_op:
        batch_op.alter_column('kind', existing_type=sa.String(length=20), nullable=False)

    with op.batch_alter_table('assignment', schema=None) as batch_op:
        batch_op.add_column(sa.Column('problems_required', sa.Integer(), nullable=True))

    op.create_table(
        'problem_attempt',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('workspace_id', sa.BigInteger(), nullable=False),
        sa.Column('document_ref', sa.String(length=40), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('answer_shown_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_submitted_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspace.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('workspace_id', 'document_ref',
                            name='uq_problem_attempt_workspace_ref'),
    )
    with op.batch_alter_table('problem_attempt', schema=None) as batch_op:
        batch_op.create_index('ix_problem_attempt_workspace', ['workspace_id'], unique=False)


def downgrade():
    with op.batch_alter_table('problem_attempt', schema=None) as batch_op:
        batch_op.drop_index('ix_problem_attempt_workspace')
    op.drop_table('problem_attempt')

    with op.batch_alter_table('assignment', schema=None) as batch_op:
        batch_op.drop_column('problems_required')

    with op.batch_alter_table('content_pack', schema=None) as batch_op:
        batch_op.drop_column('chapter_ordinal')
        batch_op.drop_column('chapter_label')
        batch_op.drop_column('textbook')
        batch_op.drop_column('kind')
