"""Checkpoints (T8.3) and submission (tension 10).

The checkpoint answer is read only inside ``grading.checkpoints.evaluate`` and only a boolean
comes back; the stored attempt holds the student's own figure, never the key's answer (A8).
"""

import pytest
from originalentry.grading.checkpoints import evaluate
from originalentry.models import Assignment, CheckpointAttempt, Section, User, Variant, Workspace
from originalentry.packs import schema
from originalentry.packs.importer import import_answer_keys, import_content
from originalentry.services import WriteRefused, workspace_write
from originalentry.services.checkpoints import checkpoint_state, record_attempt
from originalentry.services.entries import record_entry
from originalentry.services.submit import submit_workspace
from sqlalchemy import select

from tests.packs import testco_alpha

pytestmark = pytest.mark.db

ANSWER = 500000  # testco-alpha key: cp1 = Accounts Receivable after posting = 5,000.00


def _seed(session):
    pv = import_content(session, schema.load_pack(testco_alpha.PACK), source_sha256="k" * 64)
    import_answer_keys(session, pv, {"A": schema.load_answer_key(testco_alpha.KEY_A)})
    variant = session.scalars(select(Variant).where(Variant.pack_version_id == pv.id)).first()
    section = Section(name="Sec", join_code="cp-join")
    student = User(email="cp@example.edu")
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


def _attempt(session, ws, student, submitted):
    passed = evaluate(session, ws, "cp1", submitted)
    workspace_write(session, ws.public_id, student, activity_kind="checkpoint",
                    mutate=lambda s, w: record_attempt(s, w, "cp1", submitted, passed))
    return passed


def test_evaluate_reads_key_and_returns_only_boolean(session):
    ws, _ = _seed(session)
    assert evaluate(session, ws, "cp1", ANSWER) is True
    assert evaluate(session, ws, "cp1", ANSWER - 1) is False
    assert evaluate(session, ws, "missing", 0) is False


def test_wrong_then_right_and_answer_never_stored(session):
    ws, student = _seed(session)

    assert _attempt(session, ws, student, 100000) is False  # a wrong figure
    state = checkpoint_state(session, ws, "cp1")
    assert state.attempts_used == 1 and state.remaining == 2 and not state.passed

    assert _attempt(session, ws, student, ANSWER) is True
    assert checkpoint_state(session, ws, "cp1").passed

    # A8: every stored attempt holds the student's own figure, never the key's answer.
    stored = session.scalars(
        select(CheckpointAttempt.value_cents).where(CheckpointAttempt.workspace_id == ws.id)
    ).all()
    # 100000 is the student's wrong guess; ANSWER is the figure they typed on the passing attempt.
    assert set(stored) == {100000, ANSWER}


def test_locks_after_three_wrong(session):
    ws, student = _seed(session)
    for guess in (100000, 200000, 300000):
        _attempt(session, ws, student, guess)
    state = checkpoint_state(session, ws, "cp1")
    assert state.locked and not state.passed and state.remaining == 0


def test_submit_makes_workspace_read_only(session):
    ws, student = _seed(session)
    workspace_write(session, ws.public_id, student, activity_kind="submit",
                    mutate=lambda s, w: submit_workspace(s, w))
    session.refresh(ws)
    assert ws.status == "submitted" and ws.submitted_at is not None
    assert ws.submitted_late_hours == 0  # no due date on the dev assignment

    # The write path now refuses further writes.
    from originalentry.forms.entries import EntryCommand, LineCommand
    cmd = EntryCommand(journal_key="general", kind="adjusting", document_ref=None,
                       entry_date=ws.submitted_at.date(), description=None,
                       lines=[LineCommand("611", None, 100, 0), LineCommand("155", None, 0, 100)],
                       client_key="after-submit")
    with pytest.raises(WriteRefused):
        workspace_write(session, ws.public_id, student, activity_kind="save",
                        mutate=lambda s, w: record_entry(s, w, cmd))
