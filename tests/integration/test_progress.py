"""What the instructor needs from the Progress screen (I2.1–I2.3, I2.5).

Every question this screen answers is of one shape: *who is stuck, and on what?* So a row carries
how far the work has got, when it last moved, whether the student locked out of a checkpoint and
with which figures, and what their last refused save was — the thing the paper set could never
tell anyone.
"""

import pytest
from originalentry.grading.checkpoints import evaluate
from originalentry.models import Assignment, Section, User, Variant, Workspace
from originalentry.packs import schema
from originalentry.packs.importer import import_answer_keys, import_content
from originalentry.services import workspace_write
from originalentry.services.activity import record_refused_save
from originalentry.services.checkpoints import record_attempt
from originalentry.services.dispositions import set_disposition
from originalentry.services.entries import record_entry
from originalentry.services.posting import post_journal_general
from originalentry.services.progress import assignment_progress
from originalentry.services.submit import submit_workspace
from sqlalchemy import select

from tests.packs import testco_alpha

pytestmark = pytest.mark.db


def _seed(session, students=("one@example.edu",), join_code="prog-join"):
    pv = import_content(session, schema.load_pack(testco_alpha.PACK), source_sha256="p" * 64)
    import_answer_keys(session, pv, {"A": schema.load_answer_key(testco_alpha.KEY_A)})
    variant = session.scalars(select(Variant).where(Variant.pack_version_id == pv.id)).first()
    section = Section(name="Sec", join_code=join_code)
    session.add(section)
    session.flush()
    assignment = Assignment(section_id=section.id, title="December", company_policy="fixed",
                            fixed_pack_version_id=pv.id)
    session.add(assignment)
    session.flush()

    workspaces = []
    for email in students:
        student = User(email=email, given_name="Sam", family_name=email.split("@")[0])
        session.add(student)
        session.flush()
        ws = Workspace(assignment_id=assignment.id, student_id=student.id, pack_version_id=pv.id,
                       variant_id=variant.id, status="in_progress")
        session.add(ws)
        session.flush()
        workspaces.append((ws, student))
    return assignment, workspaces


def _record_sale(session, ws, student, document_ref, client_key):
    from originalentry.forms.entries import EntryCommand, LineCommand

    command = EntryCommand(
        journal_key="general", kind="regular", document_ref=document_ref,
        entry_date=__import__("datetime").date(2026, 12, 2), description=None,
        lines=[LineCommand("112", "C-ONE", 120000, 0), LineCommand("401", None, 0, 120000)],
        client_key=client_key,
    )
    workspace_write(session, ws.public_id, student, activity_kind="save",
                    mutate=lambda s, w: record_entry(s, w, command))


def test_a_workspace_nobody_has_opened_reads_as_not_started(session):
    assignment, [(ws, _)] = _seed(session)

    rows = assignment_progress(session, assignment)

    assert len(rows) == 1
    row = rows[0]
    assert row.stage == "Not started"
    assert row.documents_triaged == 0
    assert row.documents_total == 2
    assert row.journals_posted == 0
    assert row.submission_status == "open"


def test_a_row_follows_the_work_as_far_as_it_has_got(session):
    assignment, [(ws, student)] = _seed(session)
    workspace_write(session, ws.public_id, student, activity_kind="disposition",
                    mutate=lambda s, w: set_disposition(s, w, "INV-1", "record", None))
    _record_sale(session, ws, student, "INV-1", "k1")

    journalising = assignment_progress(session, assignment)[0]
    assert journalising.stage == "Journalising"
    assert journalising.documents_triaged == 1
    assert journalising.last_activity_at is not None

    workspace_write(session, ws.public_id, student, activity_kind="post",
                    mutate=lambda s, w: post_journal_general(s, w, "general"))

    posted = assignment_progress(session, assignment)[0]
    assert posted.journals_posted == 1
    assert posted.stage == "Posted"


def test_submission_shows_on_the_row(session):
    assignment, [(ws, student)] = _seed(session)
    workspace_write(session, ws.public_id, student, activity_kind="submit",
                    mutate=lambda s, w: submit_workspace(s, w))

    assert assignment_progress(session, assignment)[0].submission_status == "submitted"


def test_a_checkpoint_lockout_is_flagged_with_the_figures_submitted(session):
    assignment, [(ws, student)] = _seed(session)
    for figure in (100000, 200000, 300000):
        passed = evaluate(session, ws, "cp1", figure)
        workspace_write(session, ws.public_id, student, activity_kind="checkpoint",
                        mutate=lambda s, w, f=figure, p=passed: record_attempt(s, w, "cp1", f, p))

    row = assignment_progress(session, assignment)[0]

    assert row.locked_checkpoints
    lockout = row.locked_checkpoints[0]
    assert lockout.checkpoint_key == "cp1"
    assert lockout.figures == (100000, 200000, 300000)


def test_the_last_refused_save_says_what_the_student_was_stuck_on(session):
    assignment, [(ws, student)] = _seed(session)

    record_refused_save(session, ws, document_ref="INV-2",
                        reason="This entry is out of balance by $140.00.")

    row = assignment_progress(session, assignment)[0]

    assert row.last_refused is not None
    assert row.last_refused.document_ref == "INV-2"
    assert "out of balance" in row.last_refused.reason


def test_every_student_in_the_section_gets_a_row_in_a_stable_order(session):
    assignment, _ = _seed(session, students=("b@example.edu", "a@example.edu"))

    rows = assignment_progress(session, assignment)

    assert [row.student_email for row in rows] == ["a@example.edu", "b@example.edu"]
