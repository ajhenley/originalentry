"""A student who did everything the way the key does — built through the real services.

The golden tests A3 and A9 replay the key **in memory**, which is fast and where a marking rule
belongs. But an in-memory replay builds its own snapshot, so it cannot see a loader that drops a
field on the way out of the database. One did: entries carried no document reference, and every
component that works document by document scored zero on real work while the in-memory tests
scored full marks.

So this helper drives the same services a browser drives: triage each document, record each entry
in the journal the key uses, post to both ledgers, adjust, close, and build the statement from
their own adjusted balances. What comes out is a workspace in Postgres that grading can be pointed
at.
"""

from __future__ import annotations

from parchment.forms.entries import EntryCommand, LineCommand
from parchment.forms.statements import RowCommand, StatementCommand
from parchment.ledger.snapshot import load_snapshot
from parchment.models import Assignment, Section, User, Variant, Workspace
from parchment.packs import replay, schema
from parchment.packs.importer import import_answer_keys, import_content
from parchment.services import workspace_write
from parchment.services.dispositions import set_disposition
from parchment.services.entries import record_entry
from parchment.services.posting import post_journal_general, post_journal_subsidiary_all
from parchment.services.statements import own_figures, save_statement
from sqlalchemy import select


def build(session, pack_dict: dict, key_dict: dict, *, email: str, join_code: str,
          worked_from: dict | None = None):
    """Return (workspace, student, pack, key) for a student who followed the key exactly.

    ``worked_from`` lets a test give the student a *different* key to work from — one document
    in the wrong journal, say — while the real key is still what grading compares against. That
    is how A9 is built: one mistake, then everything afterwards handled properly on the figures
    the mistake left behind.
    """
    pack = schema.load_pack(pack_dict)
    key = schema.load_answer_key(key_dict)
    worked = schema.load_answer_key(worked_from) if worked_from else key

    pack_version = import_content(session, pack, source_sha256=join_code.ljust(64, "0"))
    import_answer_keys(session, pack_version, {key.variant: key})
    variant_id = session.scalars(
        select(Variant.id).where(
            Variant.pack_version_id == pack_version.id, Variant.code == key.variant
        )
    ).one()

    section = Section(name="Section", join_code=join_code)
    student = User(email=email, given_name="Ada", family_name="Keys")
    session.add_all([section, student])
    session.flush()
    assignment = Assignment(section_id=section.id, title="December cycle",
                            company_policy="fixed", fixed_pack_version_id=pack_version.id)
    session.add(assignment)
    session.flush()
    workspace = Workspace(assignment_id=assignment.id, student_id=student.id,
                          pack_version_id=pack_version.id, variant_id=variant_id,
                          status="in_progress")
    session.add(workspace)
    session.flush()

    _triage(session, workspace, student, worked)
    _journalise(session, workspace, student, pack, worked)
    _adjust(session, workspace, student, pack, worked)
    _post_everything(session, workspace, student, pack)
    _close(session, workspace, student, pack, worked)
    _post_everything(session, workspace, student, pack)
    _build_statements(session, workspace, student, pack)

    return workspace, student, pack, key


def _write(session, workspace, student, kind, mutate):
    workspace_write(session, workspace.public_id, student, activity_kind=kind, mutate=mutate)


def _triage(session, workspace, student, key):
    for document_ref, requires_entry in key.triage.items():
        choice = "record" if requires_entry else "no_entry"
        reason = None if requires_entry else "The key records nothing for this document."
        _write(session, workspace, student, "disposition",
               lambda s, w, r=document_ref, c=choice, why=reason: set_disposition(s, w, r, c, why))


def _journalise(session, workspace, student, pack, key):
    journals = {j.key: j for j in pack.journals}
    engine_journals = {
        j.key: replay.Journal(
            key=j.key, name=j.name, ref_prefix=j.ref_prefix, kind=j.kind,
            columns=tuple(
                replay.JournalColumn(key=c.key, label=c.label, side=c.side,
                                     account_number=c.account, posts=c.posts,
                                     subsidiary_kind=c.subsidiary_kind)
                for c in j.columns
            ),
        )
        for j in pack.journals
    }

    for index, expected in enumerate(key.expected_entries, start=1):
        journal = engine_journals.get(expected.journal)
        lines = [
            LineCommand(
                account_number=line.account,
                party_code=line.party,
                debit_cents=line.debit or 0,
                credit_cents=line.credit or 0,
                column_key=replay.column_key_for(
                    journal, line.account, "debit" if line.debit else "credit"
                ) if journal and journals[expected.journal].kind == "special" else None,
            )
            for line in expected.lines
        ]
        command = EntryCommand(
            journal_key=expected.journal,
            kind=expected.kind,
            document_ref=expected.document,
            entry_date=pack.period.start,
            description=None,
            lines=lines,
            client_key=f"expected-{index}",
        )
        _write(session, workspace, student, "save",
               lambda s, w, c=command: record_entry(s, w, c))


def _adjust(session, workspace, student, pack, key):
    general = replay.general_journal_key(pack)
    for index, adjustment in enumerate(key.adjustments, start=1):
        if adjustment.amount_basis != "independent" or adjustment.amount is None:
            continue
        lines = [
            LineCommand(
                account_number=pattern.account,
                party_code=None,
                debit_cents=adjustment.amount if pattern.side == "debit" else 0,
                credit_cents=adjustment.amount if pattern.side == "credit" else 0,
            )
            for pattern in adjustment.pattern
        ]
        command = EntryCommand(
            journal_key=general, kind="adjusting", document_ref=None,
            entry_date=pack.period.end, description=adjustment.label, lines=lines,
            client_key=f"adjustment-{index}",
        )
        _write(session, workspace, student, "save",
               lambda s, w, c=command: record_entry(s, w, c))


def _close(session, workspace, student, pack, key):
    """The four closing entries, worked out from the student's own adjusted balances."""
    from parchment.ledger import balances

    general = replay.general_journal_key(pack)
    snapshot = load_snapshot(session, workspace)
    adjusted = balances(snapshot, "adjusted")

    for index, line_set in enumerate(
        replay.closing_line_sets(pack, snapshot.accounts, adjusted), start=1
    ):
        command = EntryCommand(
            journal_key=general, kind="closing", document_ref=None,
            entry_date=pack.period.end, description="Closing entry",
            lines=[
                LineCommand(account_number=line.account_number, party_code=None,
                            debit_cents=line.debit_cents, credit_cents=line.credit_cents)
                for line in line_set
            ],
            client_key=f"closing-{index}",
        )
        _write(session, workspace, student, "save",
               lambda s, w, c=command: record_entry(s, w, c))


def _post_everything(session, workspace, student, pack):
    from parchment.models import JournalEntry
    from parchment.services.errors import WriteRefused

    journal_keys = list(
        session.scalars(
            select(JournalEntry.journal_key)
            .where(JournalEntry.workspace_id == workspace.id)
            .distinct()
        )
    )
    for journal_key in journal_keys:
        try:
            _write(session, workspace, student, "post",
                   lambda s, w, k=journal_key: post_journal_general(s, w, k))
        except WriteRefused:
            pass  # already posted: the second pass only catches the closing entries
        try:
            _write(session, workspace, student, "post",
                   lambda s, w, k=journal_key: post_journal_subsidiary_all(s, w, k))
        except WriteRefused:
            pass  # no party lines in this journal, or already posted


def _build_statements(session, workspace, student, pack):
    figures = {row["number"]: row["amount_cents"] for row in own_figures(session, workspace)}
    snapshot = load_snapshot(session, workspace)

    for definition in pack.statements:
        rows = []
        net = 0
        for number in sorted(
            figures, key=lambda n: snapshot.accounts[n].sort_order if n in snapshot.accounts else 0
        ):
            account = snapshot.accounts.get(number)
            if account is None or account.statement_section not in definition.allowed_sections:
                continue
            rows.append(RowCommand(kind="account", account_number=number,
                                   amount_cents=abs(figures[number]), indent=1))
            net -= figures[number]
        for required in definition.required_subtotals:
            rows.append(RowCommand(kind="subtotal", subtotal_type=required, amount_cents=net))
        if not rows:
            continue
        command = StatementCommand(statement_type=definition.type,
                                   header={"title": definition.title}, rows=rows)
        _write(session, workspace, student, "statement",
               lambda s, w, c=command: save_statement(s, w, c))
