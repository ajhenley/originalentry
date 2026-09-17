"""statement_draft and statement_line (S5.5, D4/D5)

Rows carry the workspace and pack version so the composite foreign keys keep a statement inside
its own company's chart. Subtotal and total rows must name a subtotal type from the pack, and an
account row must name an account: both are CHECK constraints, not conventions.

``statement_line`` is one of the four tables the web role may DELETE from, because a saved
statement replaces the student's previous layout in place (tension 9).

Revision ID: a71c3d5e9b42
Revises: d39b0238741d
Create Date: 2026-09-17 15:05:00.000000

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'a71c3d5e9b42'
down_revision = 'd39b0238741d'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'statement_draft',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('workspace_id', sa.BigInteger(), nullable=False),
        sa.Column('statement_type', sa.String(length=40), nullable=False),
        sa.Column('header', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                  nullable=False),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspace.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('workspace_id', 'statement_type'),
    )
    op.create_table(
        'statement_line',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('draft_id', sa.BigInteger(), nullable=False),
        sa.Column('workspace_id', sa.BigInteger(), nullable=False),
        sa.Column('pack_version_id', sa.BigInteger(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=12), nullable=False),
        sa.Column('label', sa.Text(), nullable=True),
        sa.Column('subtotal_type', sa.String(length=40), nullable=True),
        sa.Column('account_id', sa.BigInteger(), nullable=True),
        sa.Column('amount_cents', sa.BigInteger(), nullable=True),
        sa.Column('indent', sa.Integer(), nullable=False),
        sa.Column('amount_column', sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('heading', 'account', 'subtotal', 'total', 'blank')",
            name='statement_line_kind',
        ),
        sa.CheckConstraint(
            "(kind <> 'account') OR (account_id IS NOT NULL)",
            name='statement_line_account_row_needs_account',
        ),
        sa.CheckConstraint(
            "(kind NOT IN ('subtotal', 'total')) OR (subtotal_type IS NOT NULL)",
            name='statement_line_subtotal_row_needs_type',
        ),
        sa.ForeignKeyConstraint(['draft_id'], ['statement_draft.id'], ),
        sa.ForeignKeyConstraint(
            ['workspace_id', 'pack_version_id'],
            ['workspace.id', 'workspace.pack_version_id'],
            name='statement_line_workspace_scope', deferrable=True, initially='DEFERRED',
        ),
        sa.ForeignKeyConstraint(
            ['pack_version_id', 'account_id'],
            ['account.pack_version_id', 'account.id'],
            name='statement_line_account_scope', deferrable=True, initially='DEFERRED',
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('draft_id', 'position'),
    )

    # A saved statement replaces its rows, so the web role needs DELETE here as it does on
    # entry_line. Guarded so this is a no-op on a single-role development database.
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'riverbend_app') THEN
            GRANT DELETE ON statement_line TO riverbend_app;
          END IF;
        END $$;
        """
    )


def downgrade():
    op.drop_table('statement_line')
    op.drop_table('statement_draft')
