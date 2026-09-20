"""Per-student accommodations (I1.11, accessibility).

Extended time is not a favour; for some students it is the difference between being able to sit
the assignment and not. So the deadline a student is held to is *their* deadline: the section's,
unless the instructor has given them another.

One student's extension changes nothing for anyone else, and it is recorded with the reason given
at the time.
"""

from datetime import UTC, datetime, timedelta

import pytest
from originalentry.models import Assignment, Section, StaffAction, User, Variant, Workspace
from originalentry.packs import schema
from originalentry.packs.importer import import_content
from originalentry.services import WriteRefused, workspace_write
from originalentry.services.accommodations import (
    clear_accommodation,
    close_for,
    set_accommodation,
)
from originalentry.services.dispositions import set_disposition
from sqlalchemy import select

from tests.packs import testco_alpha

pytestmark = pytest.mark.db

YESTERDAY = datetime.now(UTC) - timedelta(days=1)
NEXT_WEEK = datetime.now(UTC) + timedelta(days=7)


@pytest.fixture
def section(session, client):
    pack_version = import_content(session, schema.load_pack(testco_alpha.PACK),
                                  source_sha256="acc" + "0" * 61)
    variant_id = session.scalars(
        select(Variant.id).where(Variant.pack_version_id == pack_version.id)
    ).first()
    sec = Section(name="ACCT 1010-07", join_code="acc-join")
    instructor = User(email="acc-instructor@example.edu", role="instructor")
    session.add_all([sec, instructor])
    session.flush()
    assignment = Assignment(section_id=sec.id, title="December", company_policy="fixed",
                            fixed_pack_version_id=pack_version.id, due_at=YESTERDAY)
    session.add(assignment)
    session.flush()

    students = []
    for email in ("needs-time@example.edu", "on-time@example.edu"):
        student = User(email=email, given_name="Sam", family_name=email[0].upper())
        session.add(student)
        session.flush()
        ws = Workspace(assignment_id=assignment.id, student_id=student.id,
                       pack_version_id=pack_version.id, variant_id=variant_id,
                       status="in_progress")
        session.add(ws)
        session.flush()
        students.append((ws, student))
    return assignment, students, instructor


def _try_to_write(session, workspace, student):
    workspace_write(session, workspace.public_id, student, activity_kind="disposition",
                    mutate=lambda s, w: set_disposition(s, w, "INV-1", "record", None))


def test_without_an_accommodation_the_section_deadline_is_the_deadline(session, section):
    assignment, [(ws, student), _], _ = section

    assert close_for(session, ws) == assignment.due_at
    with pytest.raises(WriteRefused):
        _try_to_write(session, ws, student)


def test_an_extension_lets_that_student_carry_on(session, section):
    assignment, [(ws, student), _], instructor = section

    set_accommodation(session, assignment=assignment, student=student, due_at=NEXT_WEEK,
                      reason="Approved extended time", actor=instructor)

    assert close_for(session, ws) == NEXT_WEEK
    _try_to_write(session, ws, student)  # no refusal


def test_it_changes_nothing_for_anybody_else(session, section):
    assignment, [(ws, student), (other_ws, other_student)], instructor = section
    set_accommodation(session, assignment=assignment, student=student, due_at=NEXT_WEEK,
                      reason="Approved extended time", actor=instructor)

    with pytest.raises(WriteRefused):
        _try_to_write(session, other_ws, other_student)


def test_the_reason_is_recorded_with_who_gave_it(session, section):
    assignment, [(_, student), _], instructor = section

    set_accommodation(session, assignment=assignment, student=student, due_at=NEXT_WEEK,
                      reason="Approved extended time", actor=instructor)

    action = session.scalars(
        select(StaffAction).where(StaffAction.action == "set_accommodation")
    ).one()
    assert action.reason == "Approved extended time"
    assert action.actor_id == instructor.id


def test_an_accommodation_needs_a_reason(session, section):
    assignment, [(_, student), _], instructor = section

    with pytest.raises(ValueError):
        set_accommodation(session, assignment=assignment, student=student, due_at=NEXT_WEEK,
                          reason="   ", actor=instructor)


def test_changing_an_extension_replaces_the_old_one(session, section):
    assignment, [(ws, student), _], instructor = section
    set_accommodation(session, assignment=assignment, student=student, due_at=NEXT_WEEK,
                      reason="First", actor=instructor)

    later = NEXT_WEEK + timedelta(days=3)
    set_accommodation(session, assignment=assignment, student=student, due_at=later,
                      reason="Second", actor=instructor)

    assert close_for(session, ws) == later


def test_clearing_it_puts_the_section_deadline_back(session, section):
    assignment, [(ws, student), _], instructor = section
    set_accommodation(session, assignment=assignment, student=student, due_at=NEXT_WEEK,
                      reason="Approved", actor=instructor)

    clear_accommodation(session, assignment=assignment, student=student,
                        reason="Withdrawn", actor=instructor)

    assert close_for(session, ws) == assignment.due_at
    with pytest.raises(WriteRefused):
        _try_to_write(session, ws, student)


def test_a_late_cut_off_can_be_extended_too(session, section):
    """Where the assignment accepts late work, the accommodation moves that cut-off as well."""
    assignment, [(ws, student), _], instructor = section
    assignment.late_policy = "accept_late"
    assignment.late_until = datetime.now(UTC) - timedelta(hours=1)
    session.flush()

    set_accommodation(session, assignment=assignment, student=student,
                      late_until=NEXT_WEEK, reason="Approved", actor=instructor)

    assert close_for(session, ws) == NEXT_WEEK


def test_the_progress_screen_shows_who_has_one(client, session, section):
    assignment, [(_, student), _], instructor = section
    set_accommodation(session, assignment=assignment, student=student, due_at=NEXT_WEEK,
                      reason="Approved extended time", actor=instructor)
    session.commit()
    client.sign_in(instructor)

    body = client.get(f"/staff/progress/{assignment.public_id}").get_data(as_text=True)

    assert "Extended" in body


def test_an_instructor_gives_extra_time_from_the_progress_screen(client, session, section):
    assignment, [(ws, student), _], instructor = section
    client.sign_in(instructor)

    response = client.post(
        f"/staff/progress/{assignment.public_id}/accommodation",
        data={"workspace": ws.public_id, "due_at": "2027-01-15T23:59",
              "reason": "Approved extended time"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert close_for(session, ws).year == 2027
