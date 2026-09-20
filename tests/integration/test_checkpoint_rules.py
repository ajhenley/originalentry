"""Checkpoint deadlines and stage gating (I1.2, S6.3).

A checkpoint is a self-check the student must pass before the work that depends on it. An
instructor can put a deadline on one, and can require it to be passed before a later stage — so a
student cannot spend four hours adjusting a trial balance that never agreed.

Gating is the instructor's option, not the app's default: an assignment with no rules set behaves
exactly as it did before.
"""

from datetime import UTC, date, datetime, timedelta

import pytest
from originalentry.forms.entries import EntryCommand, LineCommand
from originalentry.grading.checkpoints import evaluate
from originalentry.models import Assignment, Section, User, Variant, Workspace
from originalentry.packs import schema
from originalentry.packs.importer import import_answer_keys, import_content
from originalentry.services import WriteRefused, workspace_write
from originalentry.services.checkpoint_rules import (
    checkpoint_deadline,
    gate_refusal,
    set_checkpoint_rule,
)
from originalentry.services.checkpoints import record_attempt
from originalentry.services.entries import record_entry
from sqlalchemy import select

from tests.packs import testco_alpha

pytestmark = pytest.mark.db

ANSWER = 500000  # testco-alpha, cp1: Accounts Receivable after posting
YESTERDAY = datetime.now(UTC) - timedelta(days=1)
NEXT_WEEK = datetime.now(UTC) + timedelta(days=7)


@pytest.fixture
def workspace(session, client):
    pv = import_content(session, schema.load_pack(testco_alpha.PACK),
                        source_sha256="cpr" + "0" * 61)
    import_answer_keys(session, pv, {"A": schema.load_answer_key(testco_alpha.KEY_A)})
    variant_id = session.scalars(select(Variant.id).where(Variant.pack_version_id == pv.id)).first()
    section = Section(name="Sec", join_code="cpr-join")
    student = User(email="cpr@example.edu", given_name="Ada", family_name="Sowande")
    instructor = User(email="cpr-instructor@example.edu", role="instructor")
    session.add_all([section, student, instructor])
    session.flush()
    assignment = Assignment(section_id=section.id, title="December", company_policy="fixed",
                            fixed_pack_version_id=pv.id)
    session.add(assignment)
    session.flush()
    ws = Workspace(assignment_id=assignment.id, student_id=student.id, pack_version_id=pv.id,
                   variant_id=variant_id, status="in_progress")
    session.add(ws)
    session.flush()
    return ws, student, assignment, instructor


def _adjusting_entry(session, ws, student, client_key="adj-1"):
    command = EntryCommand(
        journal_key="general", kind="adjusting", document_ref=None,
        entry_date=date(2026, 12, 31), description="Depreciation",
        lines=[LineCommand("611", None, 25000, 0), LineCommand("155", None, 0, 25000)],
        client_key=client_key,
    )
    workspace_write(session, ws.public_id, student, activity_kind="save",
                    mutate=lambda s, w: record_entry(s, w, command))


def _pass_checkpoint(session, ws, student):
    passed = evaluate(session, ws, "cp1", ANSWER)
    workspace_write(session, ws.public_id, student, activity_kind="checkpoint",
                    mutate=lambda s, w: record_attempt(s, w, "cp1", ANSWER, passed))


# ── gating ──────────────────────────────────────────────────────────────────────────────

def test_without_a_rule_the_work_is_not_gated(session, workspace):
    ws, student, _, _ = workspace

    assert gate_refusal(session, ws, "adjusting") is None
    _adjusting_entry(session, ws, student)  # no refusal


def test_a_gated_stage_is_refused_until_the_checkpoint_is_passed(session, workspace):
    ws, student, assignment, instructor = workspace
    set_checkpoint_rule(session, assignment=assignment, ordinal=1, gates_stage="adjusting",
                        actor=instructor)

    refusal = gate_refusal(session, ws, "adjusting")
    assert refusal is not None
    assert "checkpoint 1" in refusal.lower()
    assert "adjusting" in refusal.lower()

    with pytest.raises(WriteRefused):
        _adjusting_entry(session, ws, student)


def test_passing_it_opens_the_stage(session, workspace):
    ws, student, assignment, instructor = workspace
    set_checkpoint_rule(session, assignment=assignment, ordinal=1, gates_stage="adjusting",
                        actor=instructor)
    _pass_checkpoint(session, ws, student)

    assert gate_refusal(session, ws, "adjusting") is None
    _adjusting_entry(session, ws, student, client_key="adj-2")


def test_a_gate_on_one_stage_leaves_the_others_alone(session, workspace):
    ws, student, assignment, instructor = workspace
    set_checkpoint_rule(session, assignment=assignment, ordinal=1, gates_stage="closing",
                        actor=instructor)

    assert gate_refusal(session, ws, "adjusting") is None
    _adjusting_entry(session, ws, student)
    assert gate_refusal(session, ws, "closing") is not None


# ── deadlines ───────────────────────────────────────────────────────────────────────────

def test_a_checkpoint_with_no_deadline_stays_open(session, workspace):
    ws, _, _, _ = workspace

    assert checkpoint_deadline(session, ws, "cp1") is None


def test_a_deadline_closes_the_checkpoint(session, workspace):
    ws, student, assignment, instructor = workspace
    set_checkpoint_rule(session, assignment=assignment, ordinal=1, deadline_at=YESTERDAY,
                        actor=instructor)

    assert checkpoint_deadline(session, ws, "cp1") == YESTERDAY
    with pytest.raises(WriteRefused):
        _pass_checkpoint(session, ws, student)


def test_a_students_extra_time_moves_their_checkpoint_too(session, workspace):
    """Extended time is extended time; it would be a strange accommodation that stopped here."""
    ws, student, assignment, instructor = workspace
    from originalentry.services.accommodations import set_accommodation

    set_checkpoint_rule(session, assignment=assignment, ordinal=1, deadline_at=YESTERDAY,
                        actor=instructor)
    set_accommodation(session, assignment=assignment, student=student,
                      checkpoint_extension_hours=48, reason="Approved", actor=instructor)

    assert checkpoint_deadline(session, ws, "cp1") == YESTERDAY + timedelta(hours=48)
    _pass_checkpoint(session, ws, student)  # inside their own deadline


def test_setting_a_rule_again_replaces_it(session, workspace):
    ws, _, assignment, instructor = workspace
    set_checkpoint_rule(session, assignment=assignment, ordinal=1, deadline_at=YESTERDAY,
                        actor=instructor)

    set_checkpoint_rule(session, assignment=assignment, ordinal=1, deadline_at=NEXT_WEEK,
                        gates_stage="adjusting", actor=instructor)

    assert checkpoint_deadline(session, ws, "cp1") == NEXT_WEEK
    assert gate_refusal(session, ws, "adjusting") is not None


# ── the screens ─────────────────────────────────────────────────────────────────────────

def test_an_instructor_sets_the_rules_from_the_console(client, session, workspace):
    _, _, assignment, instructor = workspace
    session.commit()
    client.sign_in(instructor)

    response = client.post(
        f"/staff/assignments/{assignment.public_id}/checkpoints",
        data={"ordinal": "1", "deadline_at": "2027-01-10T23:59", "gates_stage": "adjusting"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert checkpoint_deadline(session, workspace[0], "cp1").year == 2027


def test_the_student_sees_the_deadline_and_why_a_stage_is_shut(client, session, workspace):
    ws, student, assignment, instructor = workspace
    set_checkpoint_rule(session, assignment=assignment, ordinal=1, deadline_at=NEXT_WEEK,
                        gates_stage="adjusting", actor=instructor)
    session.commit()
    client.sign_in(student)

    body = client.get(
        f"/w/{ws.public_id}/testco-alpha/checkpoints"
    ).get_data(as_text=True)

    assert "Closes" in body
    assert "adjusting" in body.lower()
