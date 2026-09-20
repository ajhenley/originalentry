"""Retention purge (OPS-7): a section's work, assignments, enrolments and orphaned students are
hard-deleted; the section row and a student still enrolled elsewhere survive."""

import copy
import secrets
from datetime import date

import pytest
from originalentry.models import (
    Assignment,
    Enrollment,
    EntryLine,
    JournalEntry,
    Section,
    User,
    Workspace,
)
from originalentry.packs import schema
from originalentry.packs.importer import import_content
from originalentry.services import workspace_write
from originalentry.services.assignments import create_assignment, open_workspace
from originalentry.services.entries import record_entry
from originalentry.services.purge import purge_section

from tests.packs import testco_alpha

pytestmark = pytest.mark.db


def test_purge_deletes_work_and_orphaned_students(session):
    data = copy.deepcopy(testco_alpha.PACK)
    data["company"]["slug"] = f"purge-{secrets.token_hex(3)}"
    pv = import_content(session, schema.load_pack(data), source_sha256=secrets.token_hex(32))
    section = Section(name="Doomed", join_code=f"D{secrets.token_hex(3).upper()}")
    other = Section(name="Kept", join_code=f"E{secrets.token_hex(3).upper()}")
    orphan = User(email=f"orphan-{secrets.token_hex(3)}@example.edu", role="student")
    kept = User(email=f"kept-{secrets.token_hex(3)}@example.edu", role="student")
    session.add_all([section, other, orphan, kept])
    session.flush()
    session.add_all([
        Enrollment(section_id=section.id, user_id=orphan.id),
        Enrollment(section_id=section.id, user_id=kept.id),
        Enrollment(section_id=other.id, user_id=kept.id),  # kept is also in another section
    ])
    assignment = create_assignment(session, section=section, title="Dec", pack_version=pv)
    ws = open_workspace(session, assignment, orphan)
    from originalentry.forms.entries import EntryCommand, LineCommand
    workspace_write(session, ws.public_id, orphan, activity_kind="save",
                    mutate=lambda s, w: record_entry(s, w, EntryCommand(
                        journal_key="general", kind="regular", document_ref="INV-1",
                        entry_date=date(2026, 12, 2), description=None,
                        lines=[LineCommand("112", "C-ONE", 1000, 0),
                               LineCommand("401", None, 0, 1000)], client_key="pg")))
    ws_id, asg_id, orphan_id, kept_id, section_id = (
        ws.id, assignment.id, orphan.id, kept.id, section.id)

    summary = purge_section(session, section, actor=None)
    session.flush()
    session.expire_all()

    assert summary.workspaces == 1 and summary.assignments == 1 and summary.students_removed == 1
    assert session.get(Workspace, ws_id) is None
    assert session.get(Assignment, asg_id) is None
    assert session.get(User, orphan_id) is None          # orphaned → removed
    assert session.get(User, kept_id) is not None         # still enrolled elsewhere → kept
    assert session.get(Section, section_id) is not None    # the section row stays (audit target)
    assert session.execute(
        JournalEntry.__table__.select().where(JournalEntry.workspace_id == ws_id)
    ).first() is None
    assert session.execute(
        EntryLine.__table__.select().where(EntryLine.workspace_id == ws_id)
    ).first() is None
