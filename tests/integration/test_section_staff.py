"""Who teaches a section."""

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from originalentry.extensions import db
from originalentry.models import ROLE_INSTRUCTOR, SectionStaff, User
from originalentry.services.assignments import create_section


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


def test_the_model_declares_every_index_the_migration_creates(session):
    """``ix_section_staff_user`` is what ``my_section_ids`` reads once per request. The migration
    creates it, so if the model does not declare it the two disagree and the next
    ``flask db migrate`` writes a migration that drops it. This is the shape of the mistake, so
    it is pinned: any section_staff difference between the model and the live schema fails here.
    """
    context = MigrationContext.configure(session.connection())
    drift = [change for change in compare_metadata(context, db.metadata)
             if "section_staff" in str(change)]
    assert drift == [], f"the model and the schema disagree about section_staff: {drift}"
