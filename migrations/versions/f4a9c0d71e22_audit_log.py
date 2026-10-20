"""audit_log

A durable, actor-attributed trail of every privileged request and every sign-in attempt. Unlike
activity_event it is never purged, and unlike staff_action it covers reads and authentication, not
only reason-bearing mutations. See originalentry/models/people.py:AuditLog.

Revision ID: f4a9c0d71e22
Revises: d7f31b905ec4
Create Date: 2026-10-08

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'f4a9c0d71e22'
down_revision = 'd7f31b905ec4'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'audit_log',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('actor_id', sa.BigInteger(), nullable=True),
        sa.Column('actor_label', sa.String(length=320), nullable=True),
        sa.Column('actor_role', sa.String(length=16), nullable=True),
        sa.Column('action', sa.String(length=80), nullable=False),
        sa.Column('method', sa.String(length=8), nullable=True),
        sa.Column('status', sa.BigInteger(), nullable=True),
        sa.Column('target_type', sa.String(length=40), nullable=True),
        sa.Column('target_id', sa.BigInteger(), nullable=True),
        sa.Column('ip_hash', sa.String(length=64), nullable=True),
        sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()),
                  server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.ForeignKeyConstraint(['actor_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('audit_log', schema=None) as batch_op:
        batch_op.create_index('ix_audit_log_at', ['at'], unique=False)
        batch_op.create_index('ix_audit_log_actor', ['actor_id', 'at'], unique=False)
        batch_op.create_index('ix_audit_log_action', ['action', 'at'], unique=False)


def downgrade():
    with op.batch_alter_table('audit_log', schema=None) as batch_op:
        batch_op.drop_index('ix_audit_log_action')
        batch_op.drop_index('ix_audit_log_actor')
        batch_op.drop_index('ix_audit_log_at')
    op.drop_table('audit_log')
