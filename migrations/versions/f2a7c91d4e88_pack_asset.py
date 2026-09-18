"""pack_asset: document images (D3, S2.1)

The bytes live in Postgres rather than a bucket. There is no second service to secure, and an
image is reachable only through a route that checks whose workspace is asking — which is a
stronger guarantee than a signed URL, because a signed URL can be forwarded.

Revision ID: f2a7c91d4e88
Revises: e94b17c6d205
Create Date: 2026-09-18 10:40:00.000000

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'f2a7c91d4e88'
down_revision = 'e94b17c6d205'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'pack_asset',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('pack_version_id', sa.BigInteger(), nullable=False),
        sa.Column('path', sa.String(length=300), nullable=False),
        sa.Column('sha256', sa.String(length=64), nullable=False),
        sa.Column('content_type', sa.String(length=60), nullable=False),
        sa.Column('byte_size', sa.BigInteger(), nullable=False),
        sa.Column('data', sa.LargeBinary(), nullable=False),
        sa.ForeignKeyConstraint(['pack_version_id'], ['pack_version.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('pack_version_id', 'path'),
    )


def downgrade():
    op.drop_table('pack_asset')
