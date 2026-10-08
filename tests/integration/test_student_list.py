"""The admin-only roster of every student.

Read-only on purpose. The spec puts deactivating students out of scope -- "they are governed by
rosters and sections, a different thing" -- so this screen shows and finds, and changes nothing.

Assertions name specific people rather than counting rows: the suite runs against a shared
database that already holds students, so a total would be a test about today's data.
"""

import pytest
from originalentry.extensions import db
from originalentry.models import (
    ROLE_ADMIN,
    ROLE_STUDENT,
    Assignment,
    Enrollment,
    User,
    Workspace,
)

from tests.scoping_world import own_section_world, staff_account

pytestmark = pytest.mark.db


@pytest.fixture
def admin(session):
    return staff_account(session, "roster-admin@example.edu", role=ROLE_ADMIN, name="Ada")


@pytest.fixture
def instructor(session):
    return staff_account(session, "roster-teacher@example.edu", name="Lee")


def _student(session, email, given="Sam", family="Student"):
    user = User(email=email, role=ROLE_STUDENT, given_name=given, family_name=family)
    session.add(user)
    session.commit()
    return user


def _page(client, user, query=""):
    client.sign_in(user)
    response = client.get(f"/staff/students{query}")
    assert response.status_code == 200, f"did not render: {response.status_code}"
    return response.get_data(as_text=True)


def test_an_admin_sees_every_student(client, session, admin):
    one = _student(session, "roster-one@example.edu", given="Ada", family="Alpha")
    two = _student(session, "roster-two@example.edu", given="Bo", family="Beta")

    page = _page(client, admin)

    assert one.email in page
    assert two.email in page
    assert "Alpha" in page and "Beta" in page


def test_a_teacher_cannot_reach_the_student_list(client, session, instructor):
    """Every student in the install on one screen is the opposite of what scoping just did."""
    own_section_world(session, instructor)
    client.sign_in(instructor)

    assert client.get("/staff/students").status_code == 404


def test_a_student_with_no_enrolment_still_appears(client, session, admin):
    """The list is of students, not of enrolments: an account that joined nothing is exactly the
    one an administrator is looking for, and it would be invisible behind a join."""
    orphan = _student(session, "roster-orphan@example.edu", given="Noa", family="Nobody")

    assert orphan.email in _page(client, admin)


def test_the_search_filters_by_name_and_by_email(client, session, admin):
    keep = _student(session, "roster-keep@example.edu", given="Keep", family="Kelly")
    drop = _student(session, "roster-drop@example.edu", given="Drop", family="Dalton")

    by_name = _page(client, admin, "?q=Kelly")
    assert keep.email in by_name
    assert drop.email not in by_name, "the filter did not exclude anybody"

    by_email = _page(client, admin, "?q=roster-keep")
    assert keep.email in by_email
    assert drop.email not in by_email


def test_the_search_is_case_insensitive(client, session, admin):
    keep = _student(session, "roster-case@example.edu", given="Case", family="Casey")

    assert keep.email in _page(client, admin, "?q=casey")


def test_a_students_sections_and_how_they_joined_are_shown(client, session, admin):
    world = own_section_world(session, admin)
    student = _student(session, "roster-enrolled@example.edu")
    session.add(Enrollment(section_id=world["section_id"], user_id=student.id,
                           source="roster", student_number="S-4417"))
    session.commit()

    page = _page(client, admin, "?q=roster-enrolled")

    assert world["section_name"] in page, "the section they are in is not shown"
    assert "S-4417" in page, "the student number from the roster import is not shown"
    assert "roster" in page.lower(), "how they joined is not shown"


def test_the_books_column_counts_live_work_not_archived(client, session, admin):
    """An archived book is gone from the student's view, so counting it would overstate how much
    work is actually open."""
    world = own_section_world(session, admin)
    assignment = session.scalars(
        db.select(Assignment).filter_by(public_id=world["assignment"])).one()
    student = _student(session, "roster-books@example.edu")

    live = Workspace(assignment_id=assignment.id, student_id=student.id,
                     pack_version_id=world["pack_version_id"], status="in_progress")
    session.add(live)
    session.commit()
    with_one = _page(client, admin, "?q=roster-books")
    assert "in progress" in with_one.lower()

    live.archived_at = db.func.now()
    session.commit()

    page = _page(client, admin, "?q=roster-books")
    assert "in progress" not in page.lower(), "an archived book is still counted"
