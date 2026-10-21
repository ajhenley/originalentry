"""the concept the problems_best_n component carries

``packs.validate.KNOWN_COMPONENTS`` is not a private list:
``tests/guards/test_concept_tags.py::test_every_component_key_is_tagged`` asserts
KNOWN_COMPONENTS <= tagged, so adding a component key without its tag turns that guard red. An
untagged component is also a permanent "Untagged" row in the mastery view -- a dashboard that
quietly describes less than it claims.

The concept is ``debit_credit``, which is the one ``entry_accuracy`` already carries: both
components measure whether a journal entry was recorded with the right accounts, sides and
figures, and a chapter problem is that same question asked in isolation.

The concept is looked up by key rather than by id: the seeded ids in c3e71f0a95b4 are an
implementation detail of that revision, and a migration that hardcoded one would break the day
the vocabulary is reseeded.

Revision ID: b5f08c2a91d6
Revises: a6b23d41c8f7
Create Date: 2026-10-20

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'b5f08c2a91d6'
down_revision = 'a6b23d41c8f7'
branch_labels = None
depends_on = None

CONCEPT_KEY = 'debit_credit'
ARTIFACT_KEY = 'problems_best_n'


def upgrade():
    op.execute(
        "INSERT INTO concept_tag (concept_id, artifact_kind, artifact_key) "
        f"SELECT id, 'component', '{ARTIFACT_KEY}' FROM concept WHERE key = '{CONCEPT_KEY}' "
        # The unique constraint is on (artifact_kind, artifact_key), so a re-run is a no-op rather
        # than a failure -- which matters because this is the kind of revision somebody re-applies
        # while bisecting.
        "ON CONFLICT (artifact_kind, artifact_key) DO NOTHING"
    )


def downgrade():
    op.execute(
        f"DELETE FROM concept_tag WHERE artifact_kind = 'component' "
        f"AND artifact_key = '{ARTIFACT_KEY}'"
    )
