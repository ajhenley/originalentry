"""workspace.variant_id becomes nullable: a variant handed out by hand (I1.3)

An assignment can give out its variants in turn, at random, or by hand. "By hand" means there is
a real state — enrolled, with no figures yet — that the column could not hold, so choosing that
policy failed at enrolment with a not-null violation rather than waiting for the instructor.

Nothing is backfilled: every existing workspace already has a variant, and this only widens what
the column may hold.

Revision ID: a1c4e7b92f30
Revises: c6e29ab41d70
Create Date: 2026-09-19 12:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'a1c4e7b92f30'
down_revision = 'c6e29ab41d70'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column('workspace', 'variant_id', existing_type=sa.BigInteger(), nullable=True)


def downgrade():
    # Going back needs every workspace to have a variant; one waiting on its instructor does not,
    # so this fails loudly rather than inventing figures for somebody.
    op.alter_column('workspace', 'variant_id', existing_type=sa.BigInteger(), nullable=False)
