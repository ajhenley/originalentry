"""section_staff: who teaches a section

Ownership did not exist before this. Every staff member could see every student's marks and
books, because nothing recorded whose section a section was.

The backfill attaches every existing section to every account that currently holds a staff role,
so the day this deploys behaves exactly as the day before it: nobody is locked out of a class
mid-term by a migration. It also means **deploying this does not close the leak** -- an admin
closes it by pruning the attachments on the people screen.

Revision ID: b8e4a2c71f09
Revises: a1c4e7b92f30
Create Date: 2026-10-07 08:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'b8e4a2c71f09'
down_revision = 'a1c4e7b92f30'
branch_labels = None
depends_on = None

STAFF_ROLES = ('grader', 'instructor', 'admin')


def upgrade():
    op.create_table(
        'section_staff',
        sa.Column('section_id', sa.BigInteger(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('added_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                  nullable=False),
        sa.Column('added_by_id', sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(['section_id'], ['section.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
        sa.ForeignKeyConstraint(['added_by_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('section_id', 'user_id'),
    )
    op.create_index('ix_section_staff_user', 'section_staff', ['user_id'])

    # Every section to every current staff member: a deliberate no-op on behaviour.
    op.execute(sa.text("""
        INSERT INTO section_staff (section_id, user_id)
        SELECT s.id, u.id
        FROM section s
        CROSS JOIN "user" u
        WHERE u.role IN :roles
        ON CONFLICT DO NOTHING
    """).bindparams(sa.bindparam('roles', value=STAFF_ROLES, expanding=True)))


def downgrade():
    op.drop_index('ix_section_staff_user', table_name='section_staff')
    op.drop_table('section_staff')
