"""``flask staff add``: the break-glass path, and the three things it used to not say.

Shell access is the permission here -- the spec is explicit that this cannot be role-gated, and a
single admin who has lost their mailbox needs this command to recover. That is exactly why it must
not print success without having restored anything. This branch created a lockout state that did
not exist before, and until these tests the documented recovery path could not clear it.

They ask for ``client`` without sending a request: that fixture is what points ``db.session`` at
this test's transaction, so the command's writes are visible here and are rolled back afterwards.
"""

import pytest
from originalentry.extensions import db
from originalentry.models import (
    ROLE_ADMIN,
    ROLE_INSTRUCTOR,
    ROLE_STUDENT,
    StaffAction,
    User,
)
from originalentry.services import staff_actions
from originalentry.services.staffing import deactivate
from sqlalchemy import select

from tests.scoping_world import staff_account

pytestmark = pytest.mark.db


@pytest.fixture
def runner(app, client):
    return app.test_cli_runner()


@pytest.fixture
def admin(session):
    return staff_account(session, "cli-admin@example.edu", role=ROLE_ADMIN, name="Ada")


@pytest.fixture
def second_admin(session):
    return staff_account(session, "cli-admin-two@example.edu", role=ROLE_ADMIN, name="Bea")


@pytest.fixture
def instructor(session):
    return staff_account(session, "cli-instructor@example.edu", name="Lee")


@pytest.fixture
def student(session):
    return staff_account(session, "cli-student@example.edu", role=ROLE_STUDENT, name="Sam")


def _invoke(runner, app, *args, **kwargs):
    return runner.invoke(args=["staff", "add", *args], **kwargs)


def _audit(session, action, target_id):
    return session.scalars(select(StaffAction).where(
        StaffAction.action == action, StaffAction.target_table == "user",
        StaffAction.target_id == target_id)).all()


def _state(session, user):
    session.expire_all()
    return session.execute(
        select(User.role, User.deactivated_at).where(User.id == user.id)).one()


def test_it_restores_access_to_a_switched_off_account_and_says_so(
        runner, app, session, admin, instructor):
    """The whole point of a break-glass path. Before this it printed "updated as instructor" and
    left them locked out -- a success message and a locked account, read in a terminal at the
    worst possible moment."""
    deactivate(session, target=instructor, actor=admin)
    session.commit()

    result = _invoke(runner, app, instructor.email, "--role", ROLE_INSTRUCTOR)

    assert result.exit_code == 0, result.output
    role, deactivated_at = _state(session, instructor)
    assert deactivated_at is None, "printed success and left the account switched off"
    assert role == ROLE_INSTRUCTOR
    assert "reactivated" in result.output.lower()
    # Attributed to a terminal, not to a person: actor_id is None on purpose.
    [entry] = _audit(session, staff_actions.STAFF_REACTIVATED, instructor.id)
    assert entry.actor_id is None


def test_it_refuses_to_collide_with_a_student_account_unless_confirmed(
        runner, app, session, student):
    """The screen calls this an integrity problem rather than an inconvenience, and refuses. The
    terminal cannot refuse outright -- it is the recovery path -- so it asks."""
    declined = _invoke(runner, app, student.email, "--role", ROLE_INSTRUCTOR, input="n\n")
    assert declined.exit_code != 0
    assert "student" in declined.output.lower()
    role, _ = _state(session, student)
    assert role == ROLE_STUDENT, "a student's marks and a teacher's marking now share a sign-in"

    confirmed = _invoke(runner, app, student.email, "--role", ROLE_INSTRUCTOR, input="y\n")
    assert confirmed.exit_code == 0, confirmed.output
    role, _ = _state(session, student)
    assert role == ROLE_INSTRUCTOR


def test_it_warns_before_demoting_the_last_active_admin(runner, app, session, admin):
    """The reviewer traced every in-app path and the invariant holds, which makes this command the
    only way to reach zero active administrators -- the whole residual risk, not a footnote."""
    for other in session.scalars(select(User).where(
            User.role == ROLE_ADMIN, User.id != admin.id)).all():
        other.role = ROLE_INSTRUCTOR
    session.commit()

    declined = _invoke(runner, app, admin.email, "--role", ROLE_INSTRUCTOR, input="n\n")
    assert declined.exit_code != 0
    assert "last active administrator" in declined.output.lower()
    role, _ = _state(session, admin)
    assert role == ROLE_ADMIN, "nobody can reach the screen that makes administrators now"


def test_it_demotes_an_admin_without_asking_when_another_one_is_active(
        runner, app, session, admin, second_admin):
    """The warning must not fire when the invariant permits the change, or it trains the operator
    to type y without reading."""
    result = _invoke(runner, app, second_admin.email, "--role", ROLE_INSTRUCTOR)
    assert result.exit_code == 0, result.output
    assert "last active administrator" not in result.output.lower()
    role, _ = _state(session, second_admin)
    assert role == ROLE_INSTRUCTOR


def test_a_deactivated_admin_does_not_count_as_the_other_active_one(
        runner, app, session, admin, second_admin, instructor):
    """The shared helper's clause, reached from the terminal: two admin rows with one switched off
    is one administrator."""
    for other in session.scalars(select(User).where(
            User.role == ROLE_ADMIN, User.id.not_in([admin.id, second_admin.id]))).all():
        other.role = ROLE_INSTRUCTOR
    session.commit()
    deactivate(session, target=second_admin, actor=instructor)
    session.commit()

    declined = _invoke(runner, app, admin.email, "--role", ROLE_INSTRUCTOR, input="n\n")
    assert "last active administrator" in declined.output.lower()
    role, _ = _state(session, admin)
    assert role == ROLE_ADMIN


def test_creating_a_brand_new_account_still_just_works(runner, app, session):
    """The ordinary case, which none of the above may have broken."""
    result = _invoke(runner, app, "cli-brand-new@example.edu", "--role", ROLE_INSTRUCTOR)
    assert result.exit_code == 0, result.output
    assert "created" in result.output
    made = session.scalars(
        select(User).where(User.email == "cli-brand-new@example.edu")).one()
    assert made.role == ROLE_INSTRUCTOR and made.deactivated_at is None
    assert db.session is not None  # the fixture really did bind the app session to this one
