"""Reopening a workspace after it was handed in (S6.5).

Submission makes the books read-only, which is right: a mark should be taken on what was handed
in. But handing in is a button a tired student can press at eleven at night with an adjustment
still to make, and an instructor has to be able to give it back.

The trap this is written against: a reopen that does not actually reopen. If the deadline has
passed, the write path refuses on the deadline whatever the status says — so reopening past a
deadline asks for the date the student now works to, and refuses rather than pretending.
"""

from datetime import UTC, date, datetime, timedelta

import pytest
from originalentry.forms.entries import EntryCommand, LineCommand
from originalentry.models import Assignment, Section, StaffAction, User, Variant, Workspace
from originalentry.packs import schema
from originalentry.packs.importer import import_content
from originalentry.services import WriteRefused, workspace_write
from originalentry.services.entries import record_entry
from originalentry.services.submit import ReopenRefused, reopen_workspace, submit_workspace
from sqlalchemy import select

from tests.packs import testco_alpha

pytestmark = pytest.mark.db

YESTERDAY = datetime.now(UTC) - timedelta(days=1)
NEXT_WEEK = datetime.now(UTC) + timedelta(days=7)


@pytest.fixture
def workspace(session, client):
    pv = import_content(session, schema.load_pack(testco_alpha.PACK),
                        source_sha256="reo" + "0" * 61)
    variant_id = session.scalars(select(Variant.id).where(Variant.pack_version_id == pv.id)).first()
    section = Section(name="Sec", join_code="reo-join")
    student = User(email="reo@example.edu", given_name="Ada", family_name="Sowande")
    instructor = User(email="reo-instructor@example.edu", role="instructor")
    session.add_all([section, student, instructor])
    session.flush()
    assignment = Assignment(section_id=section.id, title="December", company_policy="fixed",
                            fixed_pack_version_id=pv.id, due_at=NEXT_WEEK)
    session.add(assignment)
    session.flush()
    ws = Workspace(assignment_id=assignment.id, student_id=student.id, pack_version_id=pv.id,
                   variant_id=variant_id, status="in_progress")
    session.add(ws)
    session.flush()
    return ws, student, assignment, instructor


def _record(session, ws, student, client_key="reo-1"):
    command = EntryCommand(
        journal_key="general", kind="regular", document_ref="INV-1",
        entry_date=date(2026, 12, 2), description=None,
        lines=[LineCommand("112", "C-ONE", 120000, 0), LineCommand("401", None, 0, 120000)],
        client_key=client_key,
    )
    workspace_write(session, ws.public_id, student, activity_kind="save",
                    mutate=lambda s, w: record_entry(s, w, command))


def test_a_submitted_workspace_is_read_only(session, workspace):
    """The baseline the rest of this rests on."""
    ws, student, _, _ = workspace
    submit_workspace(session, ws)

    with pytest.raises(WriteRefused):
        _record(session, ws, student)


def test_reopening_lets_the_student_work_again(session, workspace):
    ws, student, _, instructor = workspace
    submit_workspace(session, ws)

    reopen_workspace(session, ws, reason="Pressed it by accident", actor=instructor)

    assert ws.status == "in_progress"
    _record(session, ws, student)  # no refusal


def test_reopening_is_recorded_with_its_reason(session, workspace):
    ws, _, _, instructor = workspace
    submit_workspace(session, ws)

    reopen_workspace(session, ws, reason="Pressed it by accident", actor=instructor)

    # Scoped to this workspace: the suite shares a database with the running app, so an
    # instructor reopening anything for real adds a row this query would otherwise pick up.
    action = session.scalars(
        select(StaffAction).where(StaffAction.action == "reopen_workspace",
                                  StaffAction.target_id == ws.id)
    ).one()
    assert action.reason == "Pressed it by accident"


def test_reopening_needs_a_reason(session, workspace):
    ws, _, _, instructor = workspace
    submit_workspace(session, ws)

    with pytest.raises(ValueError):
        reopen_workspace(session, ws, reason="   ", actor=instructor)

    assert ws.status == "submitted"


def test_there_is_nothing_to_reopen_on_work_that_was_never_handed_in(session, workspace):
    ws, _, _, instructor = workspace

    with pytest.raises(ReopenRefused):
        reopen_workspace(session, ws, reason="Anything", actor=instructor)


def test_the_earlier_submission_is_still_on_the_record(session, workspace):
    """That they handed in, and when, is what the mark was taken on. Reopening does not erase it."""
    ws, _, _, instructor = workspace
    submit_workspace(session, ws)
    handed_in = ws.submitted_at

    reopen_workspace(session, ws, reason="Giving it back", actor=instructor)

    assert ws.submitted_at == handed_in
    assert ws.reopened_at is not None


def test_they_can_hand_it_in_again(session, workspace):
    ws, student, _, instructor = workspace
    submit_workspace(session, ws)
    reopen_workspace(session, ws, reason="Giving it back", actor=instructor)
    _record(session, ws, student)

    submit_workspace(session, ws)

    assert ws.status == "submitted"
    with pytest.raises(WriteRefused):
        _record(session, ws, student, client_key="reo-2")


# ── The trap: a deadline that has already passed ────────────────────────────────────────

def test_reopening_past_the_deadline_without_a_date_is_refused(session, workspace):
    """A reopen that leaves the student still unable to write would be worse than saying no."""
    ws, _, assignment, instructor = workspace
    assignment.due_at = YESTERDAY
    submit_workspace(session, ws)

    with pytest.raises(ReopenRefused) as refused:
        reopen_workspace(session, ws, reason="Giving it back", actor=instructor)

    assert "until" in str(refused.value).lower() or "date" in str(refused.value).lower()
    assert ws.status == "submitted"


def test_reopening_past_the_deadline_with_a_date_lets_them_write(session, workspace):
    ws, student, assignment, instructor = workspace
    assignment.due_at = YESTERDAY
    submit_workspace(session, ws)

    reopen_workspace(session, ws, reason="Giving it back", until=NEXT_WEEK, actor=instructor)

    assert ws.status == "in_progress"
    _record(session, ws, student)


def test_the_date_becomes_that_students_own_deadline(session, workspace):
    """Reopening uses the accommodation already built for one student's own deadline (I1.11)."""
    from originalentry.services.accommodations import close_for

    ws, _, assignment, instructor = workspace
    assignment.due_at = YESTERDAY
    submit_workspace(session, ws)

    reopen_workspace(session, ws, reason="Giving it back", until=NEXT_WEEK, actor=instructor)

    assert close_for(session, ws) == NEXT_WEEK


# ── The screen ──────────────────────────────────────────────────────────────────────────

def test_an_instructor_reopens_it_from_the_grading_screen(client, session, workspace):
    ws, _, assignment, instructor = workspace
    submit_workspace(session, ws)
    session.commit()
    client.sign_in(instructor)

    response = client.post(
        f"/staff/grading/{assignment.public_id}/{ws.public_id}/reopen",
        data={"reason": "Pressed it by accident"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    session.refresh(ws)
    assert ws.status == "in_progress"


def test_the_screen_says_why_it_could_not_reopen(client, session, workspace):
    ws, _, assignment, instructor = workspace
    assignment.due_at = YESTERDAY
    submit_workspace(session, ws)
    session.commit()
    client.sign_in(instructor)

    response = client.post(
        f"/staff/grading/{assignment.public_id}/{ws.public_id}/reopen",
        data={"reason": "Giving it back"},
        follow_redirects=True,
    )

    session.refresh(ws)
    assert ws.status == "submitted"
    assert "deadline" in response.get_data(as_text=True).lower()


def test_the_grading_screen_does_not_offer_it_before_anything_is_handed_in(client, session,
                                                                            workspace):
    ws, _, assignment, instructor = workspace
    session.commit()
    client.sign_in(instructor)

    body = client.get(
        f"/staff/grading/{assignment.public_id}/{ws.public_id}"
    ).get_data(as_text=True)

    assert "Give it back" not in body


def test_the_grading_screen_offers_it_once_the_work_is_in(client, session, workspace):
    ws, _, assignment, instructor = workspace
    submit_workspace(session, ws)
    session.commit()
    client.sign_in(instructor)

    body = client.get(
        f"/staff/grading/{assignment.public_id}/{ws.public_id}"
    ).get_data(as_text=True)

    assert "Give it back" in body


def test_the_remedies_do_not_wait_for_the_work_to_be_graded(client, session, workspace):
    """A student says "wrong company" or "I pressed it by accident" long before anything is
    marked. Both controls used to sit inside the marks table, so neither was reachable."""
    ws, _, assignment, instructor = workspace
    submit_workspace(session, ws)
    session.commit()
    client.sign_in(instructor)

    body = client.get(
        f"/staff/grading/{assignment.public_id}/{ws.public_id}"
    ).get_data(as_text=True)

    assert "This workspace has not been graded yet" in body
    assert "Give it back" in body
    assert "Archive and restart" in body
