"""may_see_section, and the switch that turns it off."""

import logging

import pytest
from flask_login import login_user
from originalentry.decorators import may_see_section, my_section_ids
from originalentry.models import ROLE_ADMIN, ROLE_INSTRUCTOR, SectionStaff, User

from tests.scoping_world import foreign_world, own_section_world, staff_account

pytestmark = pytest.mark.db


@pytest.fixture
def instructor(session):
    user = User(email="scoping-teacher@example.edu", role=ROLE_INSTRUCTOR)
    session.add(user)
    session.flush()
    return user


@pytest.fixture
def section(session):
    from originalentry.services.assignments import create_section
    return create_section(session, name="ACCT1010 A", term="Spring", actor=None)


def test_a_teacher_sees_a_section_they_teach(app, session, instructor, section):
    session.add(SectionStaff(section_id=section.id, user_id=instructor.id))
    session.flush()
    with app.test_request_context():
        login_user(instructor)
        assert may_see_section(section.id) is True


def test_a_teacher_does_not_see_a_section_they_do_not_teach(app, session, instructor, section):
    with app.test_request_context():
        login_user(instructor)
        assert may_see_section(section.id) is False


def test_an_admin_sees_every_section(app, session, instructor, section):
    instructor.role = ROLE_ADMIN
    session.flush()
    with app.test_request_context():
        login_user(instructor)
        assert may_see_section(section.id) is True


def test_the_sections_are_loaded_once_per_request(app, session, instructor, section):
    """workspace_view runs on every /w/ route and a console page checks several times."""
    session.add(SectionStaff(section_id=section.id, user_id=instructor.id))
    session.flush()
    with app.test_request_context():
        login_user(instructor)
        first = my_section_ids()
        assert my_section_ids() is first, "the per-request cache was not used"


def test_a_second_sign_in_is_evaluated_against_the_second_teachers_sections(client, session):
    """The cache above is per request. This harness is not.

    tests/conftest.py holds one app context open for the whole test and Flask reuses it per
    request, so anything cached on ``g`` outlives a sign-in switch -- which is why ``sign_in``
    already pops Flask-Login's own user cache. Without the same treatment for this one, a test
    that signs in teacher A, makes a request, then signs in teacher B evaluates B against A's
    sections: B is refused their own class and admitted to A's, and the shape of test most likely
    to catch a leak is the shape that silently stops testing anything. Production is unaffected,
    because there every request gets its own app context.
    """
    theirs = foreign_world(session)
    them = session.get(User, theirs["teacher_id"])
    me = staff_account(session, "cache-mine@example.edu")
    mine = own_section_world(session, me)

    client.sign_in(them)
    assert client.get(f"/staff/sections/{theirs['section_id']}/availability").status_code == 200

    client.sign_in(me)
    assert client.get(f"/staff/sections/{mine['section_id']}/availability").status_code == 200, \
        "the second teacher was refused their own section: the first teacher's cache survived"
    assert client.get(f"/staff/sections/{theirs['section_id']}/availability").status_code == 404, \
        "the second teacher was admitted to the first teacher's section"


def test_the_switch_opens_everything(monkeypatch, app, session, instructor, section):
    """Review Focus 5. The flag is a supported state in which the privacy control is absent.

    ``monkeypatch.setitem`` rather than assign-and-restore: ``app`` is session-scoped, so a flag
    left False by a failing assertion would disable the guard for every later test in the run --
    and the tests that would then pass wrongly are the scoping tests themselves.
    """
    with app.test_request_context():
        login_user(instructor)
        assert may_see_section(section.id) is False
        monkeypatch.setitem(app.config, "SCOPED_VISIBILITY", False)
        assert may_see_section(section.id) is True


def test_the_switch_being_off_is_logged_at_startup(monkeypatch, caplog):
    """A supported state in which the privacy control is absent must not be a quiet one."""
    from originalentry.app import create_app
    monkeypatch.setenv("SCOPED_VISIBILITY", "0")
    with caplog.at_level(logging.WARNING):
        app = create_app()
    assert app.config["SCOPED_VISIBILITY"] is False
    assert any("SCOPED_VISIBILITY is off" in r.getMessage() for r in caplog.records)
