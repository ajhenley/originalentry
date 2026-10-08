"""Taking access away, without taking the record away.

Two checks, two jobs. ``app.py``'s user loader kills a session that is already live; the check in
``auth.views._complete_sign_in`` refuses a *new* sign-in and says why. The second is not optional
politeness: once ``User.is_active`` stops being hardcoded ``True``, Flask-Login's ``login_user``
refuses an inactive user by itself and returns ``False``, which would land the person on a
redirect with no session and no explanation.

Nothing here is deleted. ``section_staff`` rows are the only answer to who taught a class last
term, so offboarding must not be a DELETE.
"""

import pytest
from originalentry.auth import email as email_module
from originalentry.auth import tokens
from originalentry.extensions import db
from originalentry.models import (
    ROLE_ADMIN,
    ROLE_INSTRUCTOR,
    Enrollment,
    Section,
    SectionStaff,
    StaffAction,
    User,
)
from originalentry.services import staff_actions
from originalentry.services.staffing import (
    StaffingRefused,
    deactivate,
    invite,
    reactivate,
)
from sqlalchemy import select

from tests.scoping_world import staff_account

pytestmark = pytest.mark.db


# Fixtures commit for themselves. tests/conftest.py binds the Session with
# join_transaction_mode="create_savepoint", so a commit here releases a SAVEPOINT rather than the
# outer transaction: the rows survive a view's db.session.rollback() and the teardown rollback
# still removes them. Leaning on a later fixture's commit to release an earlier one's savepoint
# works only while the tests ask for them in one particular order.

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
    return staff_account(session, "deact-admin@example.edu", role=ROLE_ADMIN, name="Ada")


@pytest.fixture
def second_admin(session):
    return staff_account(session, "deact-admin-two@example.edu", role=ROLE_ADMIN, name="Bea")


@pytest.fixture
def instructor(session):
    return staff_account(session, "deact-instructor@example.edu", name="Lee")


@pytest.fixture
def section(session):
    # Uppercase: auth.join upper-cases the submitted code and matches join_code exactly, so a
    # lower-case fixture code answers 422 and reads as a refusal that has nothing to do with the
    # account's state.
    row = Section(name="Deactivation ACCT1010-01", term="Spring", join_code="DEACTSEC01")
    session.add(row)
    session.commit()
    return row


def _audit(session, action, target_id):
    return session.scalars(select(StaffAction).where(
        StaffAction.action == action, StaffAction.target_table == "user",
        StaffAction.target_id == target_id)).all()


def _only_admin(session, keeper):
    """Exactly one administrator in this transaction, whatever the shared database holds."""
    for other in session.scalars(select(User).where(
            User.role == ROLE_ADMIN, User.id != keeper.id)).all():
        other.role = ROLE_INSTRUCTOR
    session.commit()


# ── A new sign-in is refused, with a reason, on both paths ───────────────────────────────

def test_a_valid_code_from_a_deactivated_account_is_refused_with_a_reason(
        client, session, instructor, admin):
    """A matching code proves they receive that mailbox, so naming the state tells them nothing
    they should not know. E1 governs the request step, which is untouched."""
    deactivate(session, target=instructor, actor=admin)
    session.commit()
    _raw, code = tokens.issue_token(session, instructor.email, user_id=instructor.id, ip=None)
    session.commit()

    response = client.post("/auth/code", data={"email": instructor.email, "code": code},
                           follow_redirects=True)
    assert b"no longer active" in response.data


def test_a_valid_link_from_a_deactivated_account_is_refused_with_a_reason(
        client, session, instructor, admin):
    """The same chokepoint, reached the other way.

    The magic link and the code both finish in ``_complete_sign_in``; a check placed in the code
    view instead would leave somebody holding a still-valid link to be signed in and then bounced
    by the user loader on their next request, with nothing said about why.
    """
    deactivate(session, target=instructor, actor=admin)
    session.commit()
    raw, _code = tokens.issue_token(session, instructor.email, user_id=instructor.id, ip=None)
    session.commit()

    response = client.post("/auth/verify", data={"token": raw}, follow_redirects=True)
    assert b"no longer active" in response.data
    # Refused, not signed in: the console is still closed to them.
    assert client.get("/staff/").status_code == 302


def test_a_deactivated_account_completing_a_join_link_is_not_enrolled(
        client, session, instructor, admin, section, mail):
    """The refusal must not land after the writes.

    _user_for is not a lookup for a PURPOSE_JOIN token: _join_user enrols the person and opens a
    workspace for every open assignment in the section, and only then does the refusal run -- and
    the refusal's first statement is a commit. So an offboarded teacher who still knows a live
    join code for one of their old sections could put themselves on that section's roster
    permanently, as a student, counted in its progress. No session is granted, so it is not an
    access leak; it is a committed write by a locked-out account on a refused sign-in.
    """
    deactivate(session, target=instructor, actor=admin)
    session.commit()

    joined = client.post("/auth/join", data={
        "code": section.join_code, "given_name": "Lee", "family_name": "Teacher",
        "email": instructor.email})
    assert joined.status_code == 200
    token = mail[0]["link"].rsplit("/", 1)[-1]

    response = client.post("/auth/verify", data={"token": token}, follow_redirects=True)

    assert b"no longer active" in response.data
    session.expire_all()
    assert session.scalars(select(Enrollment).where(
        Enrollment.section_id == section.id,
        Enrollment.user_id == instructor.id)).first() is None, \
        "a locked-out account enrolled itself on a refused sign-in"


def test_the_request_step_is_identical_for_active_deactivated_and_unknown_addresses(
        client, session, instructor, admin):
    """The E1 guarantee, tested directly rather than assumed. All three arms the name promises."""
    deactivate(session, target=instructor, actor=admin)
    session.commit()

    arms = {"active": admin.email,
            "deactivated": instructor.email,
            "unknown": "deact-nobody@example.edu"}
    # One POST per arm, not two. Each address has its own 3-per-15-minutes ceiling and a second
    # pass would spend two thirds of it inside one test.
    seen = {}
    for name, address in arms.items():
        response = client.post("/auth/sign-in", data={"email": address})
        seen[name] = (response.status_code, response.get_data(as_text=True))

    # The request step renders check_email.html *with the submitted address* (auth/views.py:
    # render_template("auth/check_email.html", email=email)), so the bodies necessarily differ by
    # that echoed address and a direct == would be red while E1 held perfectly. The property that
    # matters is that nothing ELSE distinguishes them, so each arm's own address is normalised out
    # before the comparison. Do not "simplify" this back into a direct comparison.
    #
    # The bodies are otherwise byte-identical for a reason worth knowing: base.html:7 renders
    # <meta name="csrf-token"> into every page, including this one, and a freshly serialised token
    # carries a one-second-resolution timestamp. They match because flask_wtf.generate_csrf caches
    # on g (flask_wtf/csrf.py:50) and this harness shares one app context across the test. Clear
    # that cache between the arms and this assertion becomes a timing coin-flip -- so whatever
    # else is done to this harness, do not reset all of g per request.
    normalised = {name: body.replace(arms[name], "SUBMITTED-ADDRESS")
                  for name, (_status, body) in seen.items()}

    assert {status for status, _body in seen.values()} == {200}
    for _status, body in seen.values():
        assert "Check your email" in body
    assert normalised["deactivated"] == normalised["unknown"] == normalised["active"]


# ── A session already live dies ──────────────────────────────────────────────────────────

def test_a_live_session_dies_on_the_next_request(client, session, instructor, admin):
    client.sign_in(instructor)
    assert client.get("/staff/").status_code == 200

    deactivate(session, target=instructor, actor=admin)
    session.commit()

    response = client.get("/staff/")
    # Exactly what @login_required does here: the unauthorized handler redirects a GET to the
    # sign-in form carrying request.full_path as ?next -- full_path keeps the trailing "?" even
    # with no query string, and url_for leaves the separators in the value unencoded. Not
    # "302 or 401 or 404": a disjunction passes whichever happens and says nothing about which
    # did, and the whole point here is that a page request lands on the sign-in form.
    assert response.status_code == 302
    assert response.headers["Location"] == "/auth/sign-in?next=/staff/?"


def test_the_user_loader_refuses_a_deactivated_account_on_a_current_epoch(
        client, session, instructor, admin):
    """The loader check on its own.

    ``deactivate`` also bumps ``session_epoch``, which invalidates every cookie issued before it,
    so the test above would stay green on a loader that had stopped looking at ``deactivated_at``
    at all. Here the cookie carries the *post*-deactivation epoch, so only the deactivation can
    refuse it.
    """
    deactivate(session, target=instructor, actor=admin)
    session.commit()

    client.sign_in(instructor)  # get_id() now carries the bumped epoch
    response = client.get("/staff/")
    assert response.status_code == 302
    assert response.headers["Location"] == "/auth/sign-in?next=/staff/?"


# ── The record survives ──────────────────────────────────────────────────────────────────

def test_their_record_survives_including_their_sections(session, instructor, admin, section):
    """Review Focus 4. Those rows are the only answer to who taught this class last term."""
    session.add(SectionStaff(section_id=section.id, user_id=instructor.id))
    session.commit()

    deactivate(session, target=instructor, actor=admin)
    session.commit()

    assert session.scalar(db.select(SectionStaff.user_id).filter_by(
        section_id=section.id, user_id=instructor.id)) == instructor.id
    assert session.scalar(db.select(User.email).where(User.id == instructor.id)) == instructor.email
    [entry] = _audit(session, staff_actions.STAFF_DEACTIVATED, instructor.id)
    assert entry.actor_id == admin.id
    # The third enforcement point, and the only one any other test reaches: the two explicit
    # checks fire first, so without this line is_active could revert to a hardcoded True and the
    # whole branch would stay green. It is what makes login_user() refuse of its own accord if
    # either explicit check is ever removed -- a future mistake becomes "no session" rather than
    # "a real session for a locked-out account".
    assert instructor.is_active is False


def test_a_section_whose_only_teacher_left_says_it_needs_one(client, session, admin, instructor,
                                                             section):
    """Review Focus 4, the other half: nobody should have to remember which sections these are."""
    session.add(SectionStaff(section_id=section.id, user_id=instructor.id))
    session.commit()
    client.sign_in(admin)
    said = f"{section.name} needs a teacher"
    assert said not in client.get("/staff/people").get_data(as_text=True)

    deactivate(session, target=instructor, actor=admin)
    session.commit()

    page = client.get("/staff/people").get_data(as_text=True)
    assert said in page


def test_reactivation_needs_a_fresh_sign_in_and_gives_the_sections_back(
        session, instructor, admin, section):
    session.add(SectionStaff(section_id=section.id, user_id=instructor.id))
    session.commit()
    cookie_before = instructor.get_id()

    deactivate(session, target=instructor, actor=admin)
    reactivate(session, target=instructor, actor=admin)
    session.commit()

    assert instructor.deactivated_at is None
    assert instructor.is_active is True        # the other half of the is_active assertion above
    # The epoch moved on the way out, so reactivating does not revive the cookie they held: they
    # sign in again.
    assert instructor.get_id() != cookie_before
    assert session.scalar(db.select(SectionStaff.user_id).filter_by(
        section_id=section.id, user_id=instructor.id)) == instructor.id
    assert _audit(session, staff_actions.STAFF_REACTIVATED, instructor.id)


# ── The refusals ─────────────────────────────────────────────────────────────────────────

def test_you_cannot_deactivate_yourself(session, admin, second_admin):
    """A second administrator exists, so only the self rule can be the one refusing."""
    with pytest.raises(StaffingRefused) as refused:
        deactivate(session, target=admin, actor=admin)
    assert "your own account" in str(refused.value)


def test_you_cannot_deactivate_the_last_admin(session, admin, instructor):
    """Somebody else is doing it, so only the last-admin rule can be the one refusing.

    This and ``test_people_screen.test_the_last_admin_cannot_be_demoted`` are the two halves of
    one invariant, and they go through one shared helper for that reason.
    """
    _only_admin(session, admin)
    with pytest.raises(StaffingRefused) as refused:
        deactivate(session, target=admin, actor=instructor)
    assert "last active administrator" in str(refused.value)
    assert session.scalar(db.select(User.deactivated_at).where(User.id == admin.id)) is None


def test_a_deactivated_admin_does_not_count_towards_the_last_admin_rule(
        session, admin, second_admin, instructor):
    """The clause the column makes possible: two admin rows, one of them switched off, is one
    administrator -- so deactivating the other would leave nobody."""
    _only_admin(session, admin)
    second_admin.role = ROLE_ADMIN
    session.commit()
    deactivate(session, target=second_admin, actor=instructor)
    session.commit()

    with pytest.raises(StaffingRefused):
        deactivate(session, target=admin, actor=instructor)


# ── The route ────────────────────────────────────────────────────────────────────────────

def test_the_route_deactivates_the_person_and_records_who_did_it(
        client, session, admin, instructor):
    """The service is also reachable, which is the only way an administrator actually uses it."""
    client.sign_in(admin)
    response = client.post(f"/staff/people/{instructor.public_id}/active",
                           data={"deactivate": "1"}, follow_redirects=True)
    assert response.status_code == 200
    session.expire_all()
    assert session.scalar(
        db.select(User.deactivated_at).where(User.id == instructor.id)) is not None
    [entry] = _audit(session, staff_actions.STAFF_DEACTIVATED, instructor.id)
    assert entry.actor_id == admin.id

    # The same POST again, which the screen never offers but a crafted body can send. Still one
    # row: a second stamp would move the date the account was switched off, and a second row
    # would say an administrator did something they did not do.
    again = client.post(f"/staff/people/{instructor.public_id}/active",
                        data={"deactivate": "1"}, follow_redirects=True)
    assert len(_audit(session, staff_actions.STAFF_DEACTIVATED, instructor.id)) == 1
    # And the screen must not report it as though something happened. A message that overstates a
    # no-op is how an operator comes to believe a second switch-off was needed.
    assert b"was already switched off. Nothing changed." in again.data
    assert b"is no longer active. Their sections and record are untouched." not in again.data


def test_the_route_reactivates_and_records_that_too(client, session, admin, instructor):
    deactivate(session, target=instructor, actor=admin)
    session.commit()
    client.sign_in(admin)
    response = client.post(f"/staff/people/{instructor.public_id}/active",
                           data={"reactivate": "1"}, follow_redirects=True)
    assert response.status_code == 200
    session.expire_all()
    assert session.scalar(db.select(User.deactivated_at).where(User.id == instructor.id)) is None
    [entry] = _audit(session, staff_actions.STAFF_REACTIVATED, instructor.id)
    assert entry.actor_id == admin.id


def test_the_route_does_nothing_at_all_for_a_post_naming_neither_direction(
        client, session, admin, instructor):
    """A security control must not default to "off".

    Reading only the deactivate field made reactivation the fallback for any POST that was not
    explicitly a deactivation, so an empty or crafted body switched the target back on and wrote
    a STAFF_REACTIVATED row saying an administrator had asked for it.
    """
    deactivate(session, target=instructor, actor=admin)
    session.commit()
    client.sign_in(admin)

    response = client.post(f"/staff/people/{instructor.public_id}/active",
                           data={}, follow_redirects=True)

    assert response.status_code == 200
    session.expire_all()
    assert session.scalar(
        db.select(User.deactivated_at).where(User.id == instructor.id)) is not None
    assert _audit(session, staff_actions.STAFF_REACTIVATED, instructor.id) == []


def test_reactivating_an_already_active_account_writes_no_audit_row(
        client, session, admin, instructor):
    """An audit trail that records things nobody did is an audit trail you cannot read."""
    client.sign_in(admin)
    response = client.post(f"/staff/people/{instructor.public_id}/active",
                           data={"reactivate": "1"}, follow_redirects=True)
    assert response.status_code == 200
    assert _audit(session, staff_actions.STAFF_REACTIVATED, instructor.id) == []


def test_inviting_an_address_whose_staff_account_is_switched_off_says_so(
        session, admin, instructor):
    """"Change their role instead" is the wrong instruction for an account that is switched off:
    changing the role would not let them in. Now that there is a switch, name the switch."""
    deactivate(session, target=instructor, actor=admin)
    session.commit()

    with pytest.raises(StaffingRefused) as refused:
        invite(session, email=instructor.email, role=ROLE_INSTRUCTOR,
               given="", family="", actor=admin)
    said = str(refused.value).lower()
    assert "switched off" in said
    assert "reactivate" in said, "the refusal must say what to do instead"


def test_the_route_refuses_the_sole_admin_switching_themselves_off(client, session, admin):
    """The refusal has to reach the screen, not only the service's caller.

    This is the one shape in which the route can reach the last-admin rule at all: ``admin_view``
    means the actor is an administrator, so any *other* target leaves the actor behind as a
    remaining one. Hence the rule is asked before the self rule -- it is the one that names the
    real problem, as ``people_role`` already argues for the demotion half.
    """
    _only_admin(session, admin)
    client.sign_in(admin)
    response = client.post(f"/staff/people/{admin.public_id}/active",
                           data={"deactivate": "1"}, follow_redirects=True)
    assert b"That is the last active administrator." in response.data
    session.expire_all()
    assert session.scalar(db.select(User.deactivated_at).where(User.id == admin.id)) is None


def test_the_route_refuses_an_admin_switching_themselves_off(client, session, admin, second_admin):
    """With a second administrator the last-admin rule permits it, so the self rule is what
    refuses -- and it must, or an administrator can lock themselves out in one click."""
    client.sign_in(admin)
    response = client.post(f"/staff/people/{admin.public_id}/active",
                           data={"deactivate": "1"}, follow_redirects=True)
    assert b"You cannot deactivate your own account." in response.data
    session.expire_all()
    assert session.scalar(db.select(User.deactivated_at).where(User.id == admin.id)) is None
