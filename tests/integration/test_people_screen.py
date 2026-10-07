"""Adding, re-roling and section-attaching staff, from inside the app."""

import pytest
from originalentry.auth import email as email_module
from originalentry.models import (
    ROLE_ADMIN,
    ROLE_INSTRUCTOR,
    ROLE_STUDENT,
    User,
)
from originalentry.services.staffing import StaffingRefused, invite
from sqlalchemy import select

from tests.scoping_world import own_section_world, staff_account

pytestmark = pytest.mark.db


@pytest.fixture
def mail(app):
    cfg = app.extensions["originalentry_config"]
    before = cfg.EMAIL_BACKEND
    cfg.EMAIL_BACKEND = "memory"
    email_module.SENT.clear()
    try:
        yield email_module.SENT
    finally:
        cfg.EMAIL_BACKEND = before
        email_module.SENT.clear()


@pytest.fixture
def admin(session):
    return staff_account(session, "people-admin@example.edu", role=ROLE_ADMIN, name="Ada")


@pytest.fixture
def second_admin(session):
    return staff_account(session, "people-admin-two@example.edu", role=ROLE_ADMIN, name="Bea")


@pytest.fixture
def instructor(session):
    return staff_account(session, "people-instructor@example.edu", name="Lee")


@pytest.fixture
def student(session):
    return staff_account(session, "people-student@example.edu", role=ROLE_STUDENT, name="Sam")


def _role_in_db(session, user):
    """The role as the database holds it, not as the identity map or the response says."""
    session.expire_all()
    return session.scalar(select(User.role).where(User.id == user.id))


def test_inviting_an_unknown_address_creates_the_account_and_sends_one_email(
        session, admin, mail):
    user = invite(session, email="new.teacher@example.edu", role=ROLE_INSTRUCTOR,
                  given="Nia", family="Okafor", actor=admin)
    session.flush()
    assert user.role == ROLE_INSTRUCTOR
    assert len(mail) == 1


def test_inviting_an_address_that_already_has_a_student_account_is_refused(session, admin, student):
    """One address being a student with marks and a teacher who reads a section's marks is an
    integrity problem, not an inconvenience. A teaching assistant is who hits this."""
    with pytest.raises(StaffingRefused) as refused:
        invite(session, email=student.email, role=ROLE_INSTRUCTOR, given="", family="", actor=admin)
    assert "student" in str(refused.value).lower()
    assert "separate" in str(refused.value).lower(), "the refusal must say what to do instead"


def test_inviting_an_address_that_differs_only_in_case_is_refused_politely(
        session, admin, student):
    """uq_user_lower_email makes this a duplicate; it must come back as a refusal rather than an
    IntegrityError from the flush."""
    with pytest.raises(StaffingRefused):
        invite(session, email=student.email.upper(), role=ROLE_INSTRUCTOR,
               given="", family="", actor=admin)


def test_inviting_an_existing_staff_address_does_not_issue_a_second_token(
        session, admin, instructor, mail):
    with pytest.raises(StaffingRefused) as refused:
        invite(session, email=instructor.email, role=ROLE_INSTRUCTOR,
               given="", family="", actor=admin)
    assert "already" in str(refused.value).lower()
    assert mail == []


def test_an_invite_is_not_throttled_by_the_per_ip_limit(session, admin, mail):
    """The ceiling is thirty an hour on the caller's IP, which would throttle an admin adding a
    department from one desk. The per-address limits that protect the recipient still apply."""
    for n in range(35):
        invite(session, email=f"t{n}@example.edu", role=ROLE_INSTRUCTOR,
               given="", family="", actor=admin)
        session.flush()
    assert len(mail) == 35


def test_an_admin_cannot_change_their_own_role(client, session, admin, second_admin):
    client.sign_in(admin)
    response = client.post(f"/staff/people/{admin.public_id}/role",
                           data={"role": ROLE_INSTRUCTOR}, follow_redirects=True)
    assert _role_in_db(session, admin) == ROLE_ADMIN
    assert b"You cannot change your own role." in response.data


def test_demoting_an_admin_takes_their_access_with_it(client, session, admin, second_admin):
    """With two administrators one may be demoted: the invariant permits it, and the demoted
    account can no longer reach the screen."""
    client.sign_in(admin)
    client.post(f"/staff/people/{second_admin.public_id}/role", data={"role": ROLE_INSTRUCTOR})
    assert _role_in_db(session, second_admin) == ROLE_INSTRUCTOR
    client.sign_in(second_admin)
    assert client.get("/staff/people").status_code == 404


def test_the_last_admin_cannot_be_demoted(client, session, admin):
    """Exactly one administrator exists, so demoting them would leave nobody able to reach the
    screen that makes administrators. The last-admin rule is asked before the own-role rule for
    this reason: it is the one that names the real problem."""
    # Exactly one admin in this transaction, whatever the shared database holds.
    for other in session.scalars(select(User).where(
            User.role == ROLE_ADMIN, User.id != admin.id)).all():
        other.role = ROLE_INSTRUCTOR
    session.commit()

    client.sign_in(admin)
    response = client.post(f"/staff/people/{admin.public_id}/role",
                           data={"role": ROLE_INSTRUCTOR}, follow_redirects=True)
    assert _role_in_db(session, admin) == ROLE_ADMIN
    assert b"That is the last administrator. Make someone else an administrator first." \
        in response.data


def test_attaching_a_section_puts_it_on_that_teachers_dashboard(client, session, admin,
                                                                instructor):
    owner = staff_account(session, "people-owner@example.edu", name="Oli")
    world = own_section_world(session, owner)
    client.sign_in(instructor)
    assert world["section_name"] not in client.get("/staff/").get_data(as_text=True)

    client.sign_in(admin)
    client.post(f"/staff/people/{instructor.public_id}/sections",
                data={"section_id": str(world["section_id"]), "attach": "1"})
    session.flush()
    client.sign_in(instructor)
    assert world["section_name"] in client.get("/staff/").get_data(as_text=True)


def test_a_teacher_cannot_reach_the_people_screen(client, instructor):
    client.sign_in(instructor)
    assert client.get("/staff/people").status_code == 404
