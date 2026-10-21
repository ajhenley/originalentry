"""workspace.staff_practice: a teacher's own private copy of their assignment

A teacher cannot see what their assignment is like to work. The staff view of a student's books is
read-only, by design and in two independent places, so the only way to try one has been to make a
fake student account. This flag marks a workspace as the teacher's own practice copy: its
``student_id`` is already the teacher's, so ownership needs nothing new, and this column is what
tells both write gates to let them type and what will keep the copy out of every class-level
number.

NOT NULL with a server default of false rather than nullable. Every workspace that exists is a
student's real work, which is what ``false`` says; a NULL would be a third state meaning "nobody
decided", and the thing being decided is whether staff may write to it. An insert that forgets
the column gets the safe answer rather than the ambiguous one.

No index. The flag is read from a workspace row already loaded by primary key or public id, and
the one query that will filter on it (a teacher's own copies) is already scoped to
``student_id``, which is indexed through the live-workspace unique index.

Revision ID: c1d7a4e63b85
Revises: b5f08c2a91d6
Create Date: 2026-10-21

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'c1d7a4e63b85'
down_revision = 'b5f08c2a91d6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'workspace',
        sa.Column('staff_practice', sa.Boolean(), nullable=False,
                  server_default=sa.text('false')),
    )


def downgrade():
    op.drop_column('workspace', 'staff_practice')
