"""Adding, re-roling and section-attaching staff, from inside the app."""

import pytest
from originalentry.auth import email as email_module
from originalentry.auth import tokens
from originalentry.models import (
    ROLE_ADMIN,
    ROLE_INSTRUCTOR,
    ROLE_STUDENT,
    SectionStaff,
    StaffAction,
    User,
)
from originalentry.services import staff_actions
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


def _audit(session, action, table, target_id):
    return session.scalars(select(StaffAction).where(
        StaffAction.action == action, StaffAction.target_table == table,
        StaffAction.target_id == target_id)).all()


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
    [entry] = _audit(session, staff_actions.STAFF_INVITED, "user", user.id)
    assert entry.actor_id == admin.id
    assert entry.detail == {"role": ROLE_INSTRUCTOR}


def test_inviting_with_a_student_role_is_refused_by_the_service(session, admin, mail):
    with pytest.raises(StaffingRefused):
        invite(session, email="sneaky@example.edu", role=ROLE_STUDENT,
               given="", family="", actor=admin)
    assert mail == []


def test_the_per_address_limits_still_apply_to_an_invite(session, mail):
    """The docstring below on the per-IP test promises this: ip=None lifts only the IP ceiling."""
    for _ in range(3):
        tokens.issue_token(session, "one.address@example.edu", ip=None)
    with pytest.raises(tokens.RateLimited):
        tokens.issue_token(session, "one.address@example.edu", ip=None)


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
    [entry] = _audit(session, staff_actions.STAFF_ROLE_CHANGED, "user", second_admin.id)
    assert entry.actor_id == admin.id
    assert entry.detail == {"from": ROLE_ADMIN, "to": ROLE_INSTRUCTOR}
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


def test_attaching_then_detaching_a_section_moves_it_on_and_off_the_dashboard(
        client, session, admin, instructor):
    owner = staff_account(session, "people-owner@example.edu", name="Oli")
    world = own_section_world(session, owner)
    sid = world["section_id"]
    url = f"/staff/people/{instructor.public_id}/sections"
    client.sign_in(instructor)
    assert world["section_name"] not in client.get("/staff/").get_data(as_text=True)

    client.sign_in(admin)
    client.post(url, data={"section_id": str(sid), "attach": "1"}, follow_redirects=True)
    session.flush()
    # create_section also recorded the owner's own attachment against this section.
    assert [e.actor_id for e in _audit(session, staff_actions.SECTION_STAFF_ADDED, "section", sid)
            if e.detail == {"user_id": instructor.id}] == [admin.id]
    client.sign_in(instructor)
    assert world["section_name"] in client.get("/staff/").get_data(as_text=True)

    client.sign_in(admin)
    client.post(url, data={"section_id": str(sid), "detach": "1"}, follow_redirects=True)
    session.expire_all()
    assert session.get(SectionStaff, (sid, instructor.id)) is None
    [removed] = _audit(session, staff_actions.SECTION_STAFF_REMOVED, "section", sid)
    assert removed.detail == {"user_id": instructor.id}
    assert removed.actor_id == admin.id, "the detach is not attributed to the admin who did it"
    client.sign_in(instructor)
    assert world["section_name"] not in client.get("/staff/").get_data(as_text=True)


def test_attaching_with_no_section_chosen_is_a_message_not_a_404(client, admin, instructor):
    """With every section already attached (Task 2's backfill) the select has no options and
    posts no section_id."""
    client.sign_in(admin)
    response = client.post(f"/staff/people/{instructor.public_id}/sections",
                           data={"attach": "1"}, follow_redirects=True)
    assert response.status_code == 200
    assert b"Choose a section." in response.data


def test_the_console_menu_links_an_admin_to_people_and_not_a_teacher(client, admin, instructor):
    client.sign_in(admin)
    assert 'href="/staff/people"' in client.get("/staff/").get_data(as_text=True)
    client.sign_in(instructor)
    page = client.get("/staff/")
    # Status first: a 404 contains no link either, so without this the negative half would
    # pass on a console that had stopped rendering altogether.
    assert page.status_code == 200
    assert 'href="/staff/people"' not in page.get_data(as_text=True)


def test_a_teacher_cannot_reach_the_people_screen(client, instructor):
    client.sign_in(instructor)
    assert client.get("/staff/people").status_code == 404
