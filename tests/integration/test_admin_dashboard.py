"""The counts an administrator sees at the top of the console.

Every assertion here is a *delta*, not a total. The suite runs against a shared database that
already holds real rows, so `assert teachers == 5` would be a test about today's data rather than
about the code. Changing one thing and asserting the matching tile moved by exactly one is also
the only way to pin what each number means -- which is where a dashboard goes quietly wrong.
"""

import re

import pytest
from originalentry.extensions import db
from originalentry.models import (
    ROLE_ADMIN,
    ROLE_INSTRUCTOR,
    ROLE_STUDENT,
    Enrollment,
    User,
)
from originalentry.services.assignments import create_section

from tests.scoping_world import own_section_world, staff_account

pytestmark = pytest.mark.db


@pytest.fixture
def admin(session):
    return staff_account(session, "dash-admin@example.edu", role=ROLE_ADMIN, name="Ada")


@pytest.fixture
def instructor(session):
    return staff_account(session, "dash-instructor@example.edu", name="Lee")


def _stat(html: str, key: str) -> int:
    """The number rendered inside the tile marked with this data-stat.

    Reads the rendered figure rather than a test-only attribute, so the test fails if the tile
    stops displaying the number it computed.
    """
    match = re.search(rf'data-stat="{key}"[^>]*>\s*<[^>]*>\s*([\d,]+)', html, re.S)
    assert match, f"no tile rendering a number for data-stat={key!r}"
    return int(match.group(1).replace(",", ""))


def _console(client, user) -> str:
    client.sign_in(user)
    response = client.get("/staff/")
    assert response.status_code == 200, f"console did not render: {response.status_code}"
    return response.get_data(as_text=True)


def test_an_admin_sees_the_dashboard(client, admin):
    page = _console(client, admin)

    for key in ("teachers", "students", "sections", "assignments", "packs", "workspaces",
                "deactivated"):
        assert f'data-stat="{key}"' in page, f"no {key} tile"


def test_a_teacher_does_not_see_the_dashboard(client, session, instructor):
    """The numbers are global on purpose, so a teacher must not be shown them at all.

    The status assertion is the point: a 404 contains no tiles either, so without it this would
    pass on a console that had stopped rendering.
    """
    own_section_world(session, instructor)
    page = _console(client, instructor)

    assert 'data-stat="teachers"' not in page
    assert 'data-stat="students"' not in page


def test_adding_a_teacher_raises_the_teacher_count_by_one(client, session, admin):
    before = _stat(_console(client, admin), "teachers")

    staff_account(session, "dash-extra@example.edu", role=ROLE_INSTRUCTOR, name="Nia")

    assert _stat(_console(client, admin), "teachers") == before + 1


def test_a_deactivated_teacher_leaves_the_teacher_count_and_joins_the_other(
        client, session, admin, instructor):
    """The definition most easily got wrong: a switched-off account is not a teacher any more,
    but it has not stopped existing either. It has to move between the two numbers, not vanish
    from one or linger in both."""
    teachers = _stat(_console(client, admin), "teachers")
    deactivated = _stat(_console(client, admin), "deactivated")

    instructor.deactivated_at = db.func.now()
    session.commit()

    page = _console(client, admin)
    assert _stat(page, "teachers") == teachers - 1, "a switched-off account still counts as staff"
    assert _stat(page, "deactivated") == deactivated + 1, "it vanished instead of moving"


def test_a_student_account_with_no_enrolment_is_not_counted(client, session, admin):
    """Students are counted by enrolment, not by account: an account exists before somebody
    joins a section, and counting it would overstate how many people are actually working."""
    before = _stat(_console(client, admin), "students")

    orphan = User(email="dash-orphan@example.edu", role=ROLE_STUDENT)
    session.add(orphan)
    session.commit()

    assert _stat(_console(client, admin), "students") == before

    section = create_section(session, name="Dash A", term="Spring", actor=admin)
    session.commit()
    session.add(Enrollment(section_id=section.id, user_id=orphan.id))
    session.commit()

    assert _stat(_console(client, admin), "students") == before + 1, "enrolling did not count"


def test_one_student_in_two_sections_is_counted_once(client, session, admin):
    """Enrolments are not people. A student repeating a course, or taking two, is one student."""
    first = create_section(session, name="Dash B", term="Spring", actor=admin)
    second = create_section(session, name="Dash C", term="Spring", actor=admin)
    student = User(email="dash-twice@example.edu", role=ROLE_STUDENT)
    session.add(student)
    session.commit()

    session.add(Enrollment(section_id=first.id, user_id=student.id))
    session.commit()
    once = _stat(_console(client, admin), "students")

    session.add(Enrollment(section_id=second.id, user_id=student.id))
    session.commit()

    assert _stat(_console(client, admin), "students") == once, "counted enrolments, not students"
