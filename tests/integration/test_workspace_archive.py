"""Archive a student's workspace and start a fresh one (I1.12). Nothing is destroyed: the old
workspace stays, archived and viewable; a fixed assignment reopens immediately."""

import copy
import secrets

import pytest
from parchment.models import Section, User, Workspace
from parchment.packs import schema
from parchment.packs.importer import import_content
from parchment.services.assignments import archive_and_restart, create_assignment, open_workspace
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
