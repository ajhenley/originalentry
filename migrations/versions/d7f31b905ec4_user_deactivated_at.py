"""user.deactivated_at: locking a staff account out without erasing them

There was no way to lock anyone out at all. ``User.is_active`` was hardcoded ``True``, and
``flask auth revoke`` only ended the sessions that existed -- the person signed straight back in.

A stamp rather than a DELETE, because ``section_staff`` rows are the only answer to *who taught
ACCT1010 last spring*. Offboarding has to take the access away and leave the record.

Nullable with no backfill: every existing account is active, which is what NULL already means.

Revision ID: d7f31b905ec4
Revises: b8e4a2c71f09
Create Date: 2026-10-07 11:30:00.000000

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'd7f31b905ec4'
down_revision = 'b8e4a2c71f09'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('user', sa.Column('deactivated_at', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column('user', 'deactivated_at')
