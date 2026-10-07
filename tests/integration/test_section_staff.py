"""Who teaches a section."""

import pytest
from originalentry.extensions import db
from originalentry.models import ROLE_INSTRUCTOR, SectionStaff, User
from originalentry.services.assignments import create_section

pytestmark = pytest.mark.db


@pytest.fixture
def instructor(session):
    user = User(email="teacher@example.edu", role=ROLE_INSTRUCTOR)
    session.add(user)
    session.flush()
    return user


def test_a_section_can_have_two_teachers(session, instructor):
    """Co-teaching is why this is a join table and not a column on Section."""
    other = User(email="second@example.edu", role=ROLE_INSTRUCTOR)
    session.add(other)
    section = create_section(session, name="ACCT1010 A", term="Spring", actor=instructor)
    session.add(SectionStaff(section_id=section.id, user_id=other.id, added_by_id=instructor.id))
    session.flush()

    teachers = set(session.scalars(
        db.select(SectionStaff.user_id).filter_by(section_id=section.id)).all())
    assert teachers == {instructor.id, other.id}


def test_creating_a_section_attaches_the_person_who_created_it(session, instructor):
    """Review Focus 1. Without this, a teacher creating an assignment with a NEW section makes a
    section nobody teaches -- and is refused from the thing they just made, one request later."""
    section = create_section(session, name="ACCT1010 B", term="Spring", actor=instructor)
    session.flush()

    attached = session.scalar(db.select(SectionStaff.user_id).filter_by(
        section_id=section.id, user_id=instructor.id))
    assert attached == instructor.id, "the creating teacher does not teach their own new section"


def test_creating_a_section_without_an_actor_attaches_nobody(session):
    """The CLI and the fixtures create sections with no actor; that must not explode."""
    section = create_section(session, name="Imported", term="Spring", actor=None)
    session.flush()
    assert session.scalars(
        db.select(SectionStaff).filter_by(section_id=section.id)).all() == []
