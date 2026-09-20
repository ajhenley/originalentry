"""Migrating a running assignment to a newer pack version (T5.5). Work is re-pointed at the new
version's content by natural key, in one transaction; a migration that would orphan work a student
has already done is refused."""

import copy
import secrets
from datetime import date

import pytest
from originalentry.models import Account, ContentPack, EntryLine, JournalEntry, Section, User
from originalentry.packs import schema
from originalentry.packs.importer import import_content
from originalentry.packs.migrate import migrate_assignment
from originalentry.services.assignments import create_assignment, open_workspace
from sqlalchemy import select, text

from tests.packs import testco_alpha

pytestmark = pytest.mark.db


def _import(session, slug, version, drop=None):
    data = copy.deepcopy(testco_alpha.PACK)
    data["company"]["slug"] = slug
    data["company"]["name"] = slug
    data["version"] = version
    if drop:
        data["accounts"] = [a for a in data["accounts"] if a["number"] != drop]
    return import_content(session, schema.load_pack(data), source_sha256=secrets.token_hex(32))


def _setup(session, slug):
    pv1 = _import(session, slug, 1)
    section = Section(name="Sec", join_code=f"M{secrets.token_hex(3).upper()}")
    student = User(email=f"m-{secrets.token_hex(3)}@example.edu", role="student")
    session.add_all([section, student])
    session.flush()
    assignment = create_assignment(session, section=section, title="Dec", pack_version=pv1)
    ws = open_workspace(session, assignment, student)
    accts = {
        a.number: a.id
        for a in session.scalars(select(Account).where(Account.pack_version_id == pv1.id))
    }
    entry = JournalEntry(workspace_id=ws.id, pack_version_id=pv1.id, journal_key="general",
                         entry_date=date(2026, 12, 2), kind="regular", client_key="m1")
    session.add(entry)
    session.flush()
    session.add_all([
        EntryLine(entry_id=entry.id, workspace_id=ws.id, pack_version_id=pv1.id, line_no=1,
                  account_id=accts["112"], debit_cents=10000, credit_cents=0),
        EntryLine(entry_id=entry.id, workspace_id=ws.id, pack_version_id=pv1.id, line_no=2,
                  account_id=accts["401"], debit_cents=0, credit_cents=10000),
    ])
    session.flush()
    return assignment, ws, pv1


def test_migrate_remaps_work_to_the_new_version(session):
    slug = f"mig-{secrets.token_hex(3)}"
    assignment, ws, pv1 = _setup(session, slug)
    pv2 = _import(session, slug, 2)

    dry = migrate_assignment(session, assignment, 2, dry_run=True)
    assert dry.feasible and dry.workspaces == 1 and dry.entry_lines == 2 and not dry.applied
    session.refresh(ws)
    assert ws.pack_version_id == pv1.id  # dry run changed nothing

    applied = migrate_assignment(session, assignment, 2, dry_run=False)
    assert applied.applied
    session.refresh(ws)
    assert ws.pack_version_id == pv2.id

    v2_accounts = {
        a.id for a in session.scalars(select(Account).where(Account.pack_version_id == pv2.id))
    }
    for line in session.scalars(select(EntryLine).where(EntryLine.workspace_id == ws.id)):
        assert line.pack_version_id == pv2.id
        assert line.account_id in v2_accounts

    # The composite foreign keys are satisfied by the new version (forced without committing).
    session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    session.rollback()


def test_migrate_refused_when_used_content_is_gone(session):
    slug = f"mig-{secrets.token_hex(3)}"
    assignment, ws, pv1 = _setup(session, slug)
    _import(session, slug, 2, drop="401")  # the student used 401; the new version drops it

    report = migrate_assignment(session, assignment, 2, dry_run=True)
    assert not report.feasible
    assert "401" in report.missing_accounts


# ── The assignment has to move too ──────────────────────────────────────────────────────
#
# Found by migrating Riverbend twice. The first migration moved every workspace and every entry
# line to version 2 and left the assignment pointing at version 1, so the second migration looked
# for workspaces on version 1, found none, and silently did nothing.
#
# The worse consequence is quieter: a student who joins after a migration is given a workspace on
# the assignment's version, which is the old one. They would be working different documents from
# the rest of their class.

def test_migrating_moves_the_assignment_itself(session):
    assignment, _, pv1 = _setup(session, f"asg-{secrets.token_hex(3)}")
    pv2 = _import(session, session.get(ContentPack, pv1.content_pack_id).slug, 2)

    migrate_assignment(session, assignment, 2, dry_run=False)

    assert assignment.fixed_pack_version_id == pv2.id


def test_a_student_joining_after_a_migration_gets_the_new_version(session):
    """The reason the pointer matters: open_workspace reads it."""
    assignment, _, pv1 = _setup(session, f"join-{secrets.token_hex(3)}")
    pv2 = _import(session, session.get(ContentPack, pv1.content_pack_id).slug, 2)
    migrate_assignment(session, assignment, 2, dry_run=False)

    latecomer = User(email=f"late-{secrets.token_hex(3)}@example.edu", role="student")
    session.add(latecomer)
    session.flush()
    workspace = open_workspace(session, assignment, latecomer)

    assert workspace.pack_version_id == pv2.id


def test_an_assignment_with_no_workspaces_still_migrates(session):
    """It used to return early before touching the assignment, so migrating before anyone had
    joined appeared to succeed and changed nothing."""
    pv1 = _import(session, slug := f"empty-{secrets.token_hex(3)}", 1)
    pv2 = _import(session, slug, 2)
    section = Section(name="Sec", join_code=f"E{secrets.token_hex(3).upper()}")
    session.add(section)
    session.flush()
    assignment = create_assignment(session, section=section, title="Dec", pack_version=pv1)

    report = migrate_assignment(session, assignment, 2, dry_run=False)

    assert report.workspaces == 0
    assert report.applied is True
    assert assignment.fixed_pack_version_id == pv2.id


def test_a_dry_run_moves_nothing(session):
    assignment, _, pv1 = _setup(session, f"dry-{secrets.token_hex(3)}")
    _import(session, session.get(ContentPack, pv1.content_pack_id).slug, 2)

    migrate_assignment(session, assignment, 2, dry_run=True)

    assert assignment.fixed_pack_version_id == pv1.id
