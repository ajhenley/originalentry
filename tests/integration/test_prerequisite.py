"""An assignment that waits for another one (M2.5).

A December cycle that only makes sense after November. The column has been on the assignment
since the first migration and was copied when an assignment was cloned, but nothing ever read it:
an instructor could set a prerequisite and every student would start anyway.

It gates *opening* the books, never writing to books already open. A student part-way through
should not have work taken away because staff changed a setting behind them.
"""

import secrets

import pytest
from originalentry.models import Enrollment, Section, User, Workspace
from originalentry.packs import schema
from originalentry.packs.importer import import_content
from originalentry.services.assignments import (
    create_assignment,
    join_with_code,
    open_workspace,
    prerequisite_met,
)
from originalentry.services.submit import submit_workspace
from sqlalchemy import select

from tests.packs import testco_alpha

pytestmark = pytest.mark.db


@pytest.fixture
def two_assignments(session, client):
    data = testco_alpha.PACK.copy()
    pv = import_content(session, schema.load_pack(data), source_sha256=secrets.token_hex(32))
    section = Section(name="Sec", join_code=f"P{secrets.token_hex(3).upper()}")
    student = User(email=f"pre-{secrets.token_hex(3)}@example.edu", role="student")
    session.add_all([section, student])
    session.flush()
    november = create_assignment(session, section=section, title="November", pack_version=pv)
    december = create_assignment(session, section=section, title="December", pack_version=pv,
                                 prerequisite=november)
    return section, student, november, december


def _enrol(session, section, student):
    session.add(Enrollment(section_id=section.id, user_id=student.id))
    session.flush()
    return join_with_code(session, code=section.join_code, student=student)


def _live(session, student, assignment):
    return session.scalars(
        select(Workspace).where(
            Workspace.student_id == student.id,
            Workspace.assignment_id == assignment.id,
            Workspace.archived_at.is_(None),
        )
    ).one_or_none()


def test_the_prerequisite_is_recorded(session, two_assignments):
    _, _, november, december = two_assignments

    assert december.prerequisite_assignment_id == november.id
    assert november.prerequisite_assignment_id is None


def test_joining_opens_only_the_one_that_is_ready(session, two_assignments):
    section, student, november, december = two_assignments

    _enrol(session, section, student)

    assert _live(session, student, november) is not None
    assert _live(session, student, december) is None


def test_handing_in_the_first_opens_the_second(session, two_assignments):
    section, student, november, december = two_assignments
    _enrol(session, section, student)
    submit_workspace(session, _live(session, student, november))

    opened = open_workspace(session, december, student)

    assert opened is not None
    assert _live(session, student, december) is not None


def test_until_then_it_stays_shut(session, two_assignments):
    section, student, _, december = two_assignments
    _enrol(session, section, student)

    assert open_workspace(session, december, student) is None
    assert prerequisite_met(session, december, student) is False


def test_an_assignment_with_no_prerequisite_is_always_ready(session, two_assignments):
    _, student, november, _ = two_assignments

    assert prerequisite_met(session, november, student) is True


def test_work_already_open_is_never_taken_away(session, two_assignments):
    """The setting gates opening, not writing. A student part-way through keeps their books even
    if staff add a prerequisite behind them."""
    section, student, november, december = two_assignments
    _enrol(session, section, student)
    submit_workspace(session, _live(session, student, november))
    open_workspace(session, december, student)

    december.prerequisite_assignment_id = november.id  # still set, and they are already in
    session.flush()

    assert _live(session, student, december) is not None
    assert open_workspace(session, december, student) is not None


def test_a_prerequisite_that_is_only_started_is_not_enough(session, two_assignments):
    """Completed means handed in. Opening the books is not completing them."""
    section, student, november, december = two_assignments
    _enrol(session, section, student)

    assert _live(session, student, november) is not None   # started
    assert prerequisite_met(session, december, student) is False


# ── The screens ─────────────────────────────────────────────────────────────────────────

def test_home_says_what_the_student_is_waiting_for(client, session, two_assignments):
    section, student, november, december = two_assignments
    _enrol(session, section, student)
    session.commit()
    client.sign_in(student)

    body = client.get("/home").get_data(as_text=True)

    assert "December" in body
    assert "November" in body          # named, so they know what to do about it


def test_an_instructor_sets_it_when_creating_the_assignment(client, session, two_assignments):
    section, _, november, _ = two_assignments
    instructor = User(email=f"pi-{secrets.token_hex(3)}@example.edu", role="instructor")
    session.add(instructor)
    session.commit()
    client.sign_in(instructor)

    body = client.get("/staff/assignments/new").get_data(as_text=True)

    assert "prerequisite" in body.lower()
    assert november.public_id in body
