"""concept, concept_tag: one accounting vocabulary and what it attaches to

Seeded in the same revision as the tables, because an empty vocabulary is not a usable state: the
mastery view would render nothing and look finished. See
originalentry/models/concepts.py and
docs/superpowers/specs/2026-10-19-concept-tagging-and-mastery-design.md.

The seed is the spec's list, copied. It is deliberately not derived from the packs at migration
time: a migration that read pack sources would produce a different vocabulary on a machine with
different packs, and the whole point of the list is that it is the same everywhere.

Revision ID: c3e71f0a95b4
Revises: f4a9c0d71e22
Create Date: 2026-10-20

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'c3e71f0a95b4'
down_revision = 'f4a9c0d71e22'
branch_labels = None
depends_on = None


#: (key, label, group, ordinal). Process concepts are scored, so they carry a share of marks.
#: Topic concepts are recognised from an error signature, which carries no marks, so they are
#: counted in students.
CONCEPTS = [
    ("document_triage", "Document triage", "process", 1),
    ("journal_selection", "Journal selection", "process", 2),
    ("debit_credit", "Debit/credit and account classification", "process", 3),
    ("posting", "Posting to ledgers", "process", 4),
    ("subsidiary_control", "Subsidiary ledger agrees with control", "process", 5),
    ("adjusting_entries", "Adjusting entries", "process", 6),
    ("statements", "Financial statement preparation", "process", 7),
    ("closing", "Closing the books", "process", 8),
    ("unearned_revenue", "Unearned revenue and deposits", "topic", 1),
    ("cash_discounts", "Cash discounts and discount periods", "topic", 2),
    ("contra_revenue", "Contra-revenue versus netting", "topic", 3),
    ("shipping_terms", "Shipping terms and freight", "topic", 4),
    ("received_vs_billed", "Goods received versus billed", "topic", 5),
    ("product_vs_period", "Product versus period cost", "topic", 6),
    ("direct_vs_indirect", "Direct versus indirect materials and labour", "topic", 7),
    ("cost_vs_price", "Cost versus selling price on transfer", "topic", 8),
    ("owner_withdrawals", "Owner's withdrawals versus expense", "topic", 9),
    ("depreciation", "Depreciation", "topic", 10),
]

#: Every key in packs.validate.KNOWN_COMPONENTS, so no known component sits in the screen's
#: transitional "Untagged" row permanently.
COMPONENT_TAGS = [
    ("document_triage", "triage"),
    ("journal_selection", "journal_selection"),
    ("debit_credit", "entry_accuracy"),
    ("posting", "posting_completeness"),
    ("subsidiary_control", "subsidiary_agreement"),
    ("adjusting_entries", "adjustment_form"),
    ("adjusting_entries", "adjustment_amounts"),
    ("statements", "statements_structure"),
    ("statements", "statements_figures"),
    ("closing", "closing"),
]

#: Every error-signature key any pack source declares. An untagged signature is dropped from the
#: mistakes block, which would make it a misconception the screen cannot name.
SIGNATURE_TAGS = [
    ("unearned_revenue", "deposit"),
    ("cash_discounts", "earlydisc"),
    ("cash_discounts", "shortpay"),
    ("cash_discounts", "purchdisc"),
    ("contra_revenue", "refund"),
    ("shipping_terms", "freight"),
    ("received_vs_billed", "receiving"),
    ("product_vs_period", "period_cost"),
    ("direct_vs_indirect", "indirect_materials"),
    ("direct_vs_indirect", "indirect_labour"),
    ("cost_vs_price", "transfer_at_price"),
    ("owner_withdrawals", "owners_draw"),
    ("depreciation", "depr_on_wrong_doc"),
]


def upgrade():
    concept = op.create_table(
        'concept',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(length=40), nullable=False),
        sa.Column('label', sa.String(length=120), nullable=False),
        sa.Column('group', sa.String(length=10), nullable=False),
        sa.Column('ordinal', sa.Integer(), nullable=False),
        sa.Column('retired_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key'),
    )
    concept_tag = op.create_table(
        'concept_tag',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('concept_id', sa.Integer(), nullable=False),
        sa.Column('artifact_kind', sa.String(length=10), nullable=False),
        sa.Column('artifact_key', sa.String(length=60), nullable=False),
        sa.ForeignKeyConstraint(['concept_id'], ['concept.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('artifact_kind', 'artifact_key', name='uq_concept_tag_artifact'),
    )
    with op.batch_alter_table('concept_tag', schema=None) as batch_op:
        batch_op.create_index('ix_concept_tag_kind_key', ['artifact_kind', 'artifact_key'],
                              unique=False)

    op.bulk_insert(concept, [
        {"id": index, "key": key, "label": label, "group": group, "ordinal": ordinal}
        for index, (key, label, group, ordinal) in enumerate(CONCEPTS, start=1)
    ])
    ids = {key: index for index, (key, _l, _g, _o) in enumerate(CONCEPTS, start=1)}
    op.bulk_insert(concept_tag, [
        {"concept_id": ids[concept_key], "artifact_kind": kind, "artifact_key": artifact_key}
        for kind, pairs in (("component", COMPONENT_TAGS), ("signature", SIGNATURE_TAGS))
        for concept_key, artifact_key in pairs
    ])
    # The ids above are assigned by hand so the tags can reference them in the same revision.
    # Postgres does not know that, so its sequence still starts at 1 and the next insert would
    # collide with a seeded row.
    op.execute("SELECT setval(pg_get_serial_sequence('concept', 'id'), "
               "(SELECT MAX(id) FROM concept))")
    op.execute("SELECT setval(pg_get_serial_sequence('concept_tag', 'id'), "
               "(SELECT MAX(id) FROM concept_tag))")


def downgrade():
    with op.batch_alter_table('concept_tag', schema=None) as batch_op:
        batch_op.drop_index('ix_concept_tag_kind_key')
    op.drop_table('concept_tag')
    op.drop_table('concept')
