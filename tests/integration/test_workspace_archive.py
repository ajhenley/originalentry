"""Archive a student's workspace and start a fresh one (I1.12). Nothing is destroyed: the old
workspace stays, archived and viewable; a fixed assignment reopens immediately."""

import copy
import secrets

import pytest
from originalentry.models import ContentPack, Section, User, Workspace
from originalentry.packs import schema
from originalentry.packs.importer import import_content
from originalentry.services.assignments import (
    archive_and_restart,
    create_assignment,
    open_workspace,
)
from sqlalchemy import func, select

from tests.packs import testco_alpha

pytestmark = pytest.mark.db


def _pack(session):
    data = copy.deepcopy(testco_alpha.PACK)
    data["company"]["slug"] = f"arch-{secrets.token_hex(3)}"
    return import_content(session, schema.load_pack(data), source_sha256=secrets.token_hex(32))


def test_archive_keeps_the_old_and_opens_a_fresh_one(session):
    pv = _pack(session)
    section = Section(name="Sec", join_code=f"A{secrets.token_hex(3).upper()}")
    student = User(email=f"a-{secrets.token_hex(3)}@example.edu", role="student")
    session.add_all([section, student])
    session.flush()
    assignment = create_assignment(session, section=section, title="Dec", pack_version=pv)
    old = open_workspace(session, assignment, student)

    fresh = archive_and_restart(session, old, reason="recorded into the wrong books")
    session.flush()

    assert old.archived_at is not None            # kept, not deleted
    assert fresh is not None and fresh.id != old.id
    assert fresh.archived_at is None

    # Exactly one live workspace for the pair (the partial unique index permits the archived one).
    live = session.execute(
        select(func.count()).select_from(Workspace).where(
            Workspace.assignment_id == assignment.id,
            Workspace.student_id == student.id,
            Workspace.archived_at.is_(None),
        )
    ).scalar_one()
    assert live == 1
    total = session.execute(
        select(func.count()).select_from(Workspace).where(
            Workspace.assignment_id == assignment.id, Workspace.student_id == student.id
        )
    ).scalar_one()
    assert total == 2  # the archived one survives


# ── "The archived books stay viewable" ──────────────────────────────────────────────────
#
# Both the console and the flash after archiving promise this. The promise is the whole reason
# archiving is safe to offer: an instructor who clears a student's work has to be able to answer
# "what was in there?" a week later, when the question turns out to be about a mark.

@pytest.fixture
def archived(session, client):
    pv = _pack(session)
    pack = session.get(ContentPack, pv.content_pack_id)
    section = Section(name="Sec", join_code=f"V{secrets.token_hex(3).upper()}")
    student = User(email=f"v-{secrets.token_hex(3)}@example.edu", role="student",
                   given_name="Ola", family_name="Bello")
    instructor = User(email=f"vi-{secrets.token_hex(3)}@example.edu", role="instructor")
    session.add_all([section, student, instructor])
    session.flush()
    assignment = create_assignment(session, section=section, title="Dec", pack_version=pv)
    old = open_workspace(session, assignment, student)
    archive_and_restart(session, old, reason="recorded into the wrong books")
    session.commit()
    return old, pack.slug, student, instructor, assignment


def test_staff_can_still_open_archived_books(client, archived):
    old, slug, _, instructor, _ = archived
    client.sign_in(instructor)

    response = client.get(f"/w/{old.public_id}/{slug}/journals/general")

    assert response.status_code == 200
    assert "archived" in response.get_data(as_text=True).lower()


def test_archived_books_cannot_be_written_to(client, archived):
    """Read-only in the strongest sense: the student has moved on to a fresh set."""
    old, slug, _, instructor, _ = archived
    client.sign_in(instructor)

    body = client.get(f"/w/{old.public_id}/{slug}/journals/general").get_data(as_text=True)

    assert "read-only" in body.lower() or "read only" in body.lower()


def test_the_student_cannot_open_the_books_that_were_taken_away(client, archived):
    old, slug, student, _, _ = archived
    client.sign_in(student)

    assert client.get(f"/w/{old.public_id}/{slug}/journals/general").status_code == 404


def test_the_console_offers_a_way_back_to_them(client, archived):
    """Viewable is no use if nothing links to it."""
    old, _, _, instructor, assignment = archived
    client.sign_in(instructor)

    body = client.get(f"/staff/grading/{assignment.public_id}").get_data(as_text=True)

    assert old.public_id in body
