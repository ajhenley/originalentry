"""may_see_section, and the switch that turns it off."""

import logging

import pytest
from flask import g
from flask_login import login_user
from originalentry.decorators import may_see_section, my_section_ids
from originalentry.models import ROLE_ADMIN, ROLE_INSTRUCTOR, SectionStaff, User

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


def test_the_switch_opens_everything(app, session, instructor, section):
    """Review Focus 5. The flag is a supported state in which the privacy control is absent."""
    with app.test_request_context():
        login_user(instructor)
        assert may_see_section(section.id) is False
        app.config["SCOPED_VISIBILITY"] = False
        g.pop("_my_section_ids", None)
        assert may_see_section(section.id) is True
    app.config["SCOPED_VISIBILITY"] = True


def test_the_switch_being_off_is_logged_at_startup(monkeypatch, caplog):
    """A supported state in which the privacy control is absent must not be a quiet one."""
    from originalentry.app import create_app
    monkeypatch.setenv("SCOPED_VISIBILITY", "0")
    with caplog.at_level(logging.WARNING):
        app = create_app()
    assert app.config["SCOPED_VISIBILITY"] is False
    assert any("SCOPED_VISIBILITY is off" in r.getMessage() for r in caplog.records)
