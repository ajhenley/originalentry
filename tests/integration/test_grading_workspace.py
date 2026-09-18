"""Grading a real workspace (T8.1).

``load_work`` is the one place that turns database rows into what the engine sees, and
``grade_workspace`` puts the pack and the variant's key beside it. The key is read here and
nowhere a student route can reach (D6 rule 6).
"""

import pytest
from parchment.forms.statements import RowCommand, StatementCommand
from parchment.grading.workspace import grade_workspace, load_work
from parchment.models import Assignment, Section, User, Variant, Workspace
from parchment.packs import schema
from parchment.packs.importer import import_answer_keys, import_content
from parchment.services import workspace_write
from parchment.services.dispositions import set_disposition
from parchment.services.statements import save_statement
from sqlalchemy import select

from tests.packs import testco_alpha

pytestmark = pytest.mark.db


def _seed(session):
    pv = import_content(session, schema.load_pack(testco_alpha.PACK), source_sha256="g" * 64)
    import_answer_keys(session, pv, {"A": schema.load_answer_key(testco_alpha.KEY_A)})
    variant = session.scalars(select(Variant).where(Variant.pack_version_id == pv.id)).first()
    section = Section(name="Sec", join_code="grade-join")
    student = User(email="grade@example.edu")
    session.add_all([section, student])
    session.flush()
    asg = Assignment(section_id=section.id, title="Dec", company_policy="fixed",
                     fixed_pack_version_id=pv.id)
    session.add(asg)
    session.flush()
    ws = Workspace(assignment_id=asg.id, student_id=student.id, pack_version_id=pv.id,
                   variant_id=variant.id, status="in_progress")
    session.add(ws)
    session.flush()
    return ws, student


def test_load_work_carries_the_triage_and_the_statements_the_student_made(session):
    ws, student = _seed(session)
    workspace_write(session, ws.public_id, student, activity_kind="disposition",
                    mutate=lambda s, w: set_disposition(s, w, "INV-1", "record", None))
    workspace_write(session, ws.public_id, student, activity_kind="disposition",
                    mutate=lambda s, w: set_disposition(s, w, "INV-2", "no_entry", "a duplicate"))
    command = StatementCommand(
        statement_type="income_statement",
        header={"title": "Income Statement"},
        rows=[RowCommand(kind="account", account_number="401", amount_cents=200000)],
    )
    workspace_write(session, ws.public_id, student, activity_kind="statement",
                    mutate=lambda s, w: save_statement(s, w, command))

    work = load_work(session, ws)

    assert work.dispositions == {"INV-1": "record", "INV-2": "no_entry"}
    assert work.disposition_reasons["INV-2"] == "a duplicate"
    rows = work.statements["income_statement"]
    assert rows[0].account_number == "401" and rows[0].amount_cents == 200000


def test_grading_an_untouched_workspace_scores_nothing_and_names_no_error(session):
    ws, _ = _seed(session)

    result = grade_workspace(session, ws)

    assert result.total_points == 0
    assert result.max_points == 100
    assert result.signatures == ()  # nothing recorded is not a designed error


def test_grading_credits_the_triage_a_student_has_done(session):
    ws, student = _seed(session)
    workspace_write(session, ws.public_id, student, activity_kind="disposition",
                    mutate=lambda s, w: set_disposition(s, w, "INV-1", "record", None))

    result = grade_workspace(session, ws)

    triage = result.component("triage")
    assert triage.points == pytest.approx(triage.max_points / 2)


def test_an_entry_carries_the_document_it_records(session):
    """Without this, every component that works document by document quietly scores zero."""
    from datetime import date

    from parchment.forms.entries import EntryCommand, LineCommand
    from parchment.services.entries import record_entry

    ws, student = _seed(session)
    command = EntryCommand(
        journal_key="general", kind="regular", document_ref="INV-1",
        entry_date=date(2026, 12, 2), description=None,
        lines=[LineCommand("112", "C-ONE", 120000, 0), LineCommand("401", None, 0, 120000)],
        client_key="doc-ref-1",
    )
    workspace_write(session, ws.public_id, student, activity_kind="save",
                    mutate=lambda s, w: record_entry(s, w, command))

    work = load_work(session, ws)

    assert len(work.entries_for_document("INV-1")) == 1
    accuracy = grade_workspace(session, ws).component("entry_accuracy")
    assert accuracy.points > 0  # the document was recognised and its entry compared
