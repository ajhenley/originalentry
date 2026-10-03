"""Migrating a running assignment to a newer pack version (T5.5). Work is re-pointed at the new
version's content by natural key, in one transaction; a migration that would orphan work a student
has already done is refused."""

import copy
import secrets
from datetime import date

import pytest
from originalentry.models import Account, EntryLine, JournalEntry, Section, SourceDocument, User
from originalentry.packs import schema
from originalentry.packs.importer import import_content
from originalentry.packs.migrate import migrate_assignment
from originalentry.services.assignments import create_assignment, open_workspace
from sqlalchemy import select, text

from tests.packs import testco_alpha

pytestmark = pytest.mark.db

#: The account the student's entry in `_setup` credits -- the one `test_migrate_refused_when_
#: used_content_is_gone` drops from version 2, and reused wherever a test needs used content to
#: disappear rather than invent a different one.
USED_ACCOUNT_NUMBER = "401"


def _import(session, slug, version, drop=None):
    data = copy.deepcopy(testco_alpha.PACK)
    data["company"]["slug"] = slug
    data["company"]["name"] = slug
    data["version"] = version
    if drop:
        data["accounts"] = [a for a in data["accounts"] if a["number"] != drop]
    return import_content(session, schema.load_pack(data), source_sha256=secrets.token_hex(32))


def _setup(session, slug):
    """Returns (assignment, workspace, used_ref): a workspace with one posted entry against a
    document the student actually used, so identity-change tests have a used ref to work with.

    The section is named after the company slug for readability; callers keep their own `slug`
    local to re-import a later version of the same company.
    """
    pv1 = _import(session, slug, 1)
    section = Section(name=slug, join_code=f"M{secrets.token_hex(3).upper()}")
    student = User(email=f"m-{secrets.token_hex(3)}@example.edu", role="student")
    session.add_all([section, student])
    session.flush()
    assignment = create_assignment(session, section=section, title="Dec", pack_version=pv1)
    ws = open_workspace(session, assignment, student)
    accts = {
        a.number: a.id
        for a in session.scalars(select(Account).where(Account.pack_version_id == pv1.id))
    }
    used_ref = "INV-1"
    document_id = session.scalars(
        select(SourceDocument.id).where(SourceDocument.pack_version_id == pv1.id,
                                        SourceDocument.ref == used_ref)
    ).one()
    entry = JournalEntry(workspace_id=ws.id, pack_version_id=pv1.id, journal_key="general",
                         entry_date=date(2026, 12, 2), kind="regular", client_key="m1",
                         document_id=document_id)
    session.add(entry)
    session.flush()
    session.add_all([
        EntryLine(entry_id=entry.id, workspace_id=ws.id, pack_version_id=pv1.id, line_no=1,
                  account_id=accts["112"], debit_cents=10000, credit_cents=0),
        EntryLine(entry_id=entry.id, workspace_id=ws.id, pack_version_id=pv1.id, line_no=2,
                  account_id=accts[USED_ACCOUNT_NUMBER], debit_cents=0, credit_cents=10000),
    ])
    session.flush()
    return assignment, ws, used_ref


def test_migrate_remaps_work_to_the_new_version(session):
    slug = f"mig-{secrets.token_hex(3)}"
    assignment, ws, _ = _setup(session, slug)
    pv1_id = ws.pack_version_id
    pv2 = _import(session, slug, 2)

    dry = migrate_assignment(session, assignment, 2, dry_run=True)
    assert dry.feasible and dry.workspaces == 1 and dry.entry_lines == 2 and not dry.applied
    session.refresh(ws)
    assert ws.pack_version_id == pv1_id  # dry run changed nothing

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
    assignment, ws, _ = _setup(session, slug)
    _import(session, slug, 2, drop=USED_ACCOUNT_NUMBER)

    report = migrate_assignment(session, assignment, 2, dry_run=True)
    assert not report.feasible
    assert USED_ACCOUNT_NUMBER in report.missing_accounts


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
    slug = f"asg-{secrets.token_hex(3)}"
    assignment, _, _ = _setup(session, slug)
    pv2 = _import(session, slug, 2)

    migrate_assignment(session, assignment, 2, dry_run=False)

    assert assignment.fixed_pack_version_id == pv2.id


def test_a_student_joining_after_a_migration_gets_the_new_version(session):
    """The reason the pointer matters: open_workspace reads it."""
    slug = f"join-{secrets.token_hex(3)}"
    assignment, _, _ = _setup(session, slug)
    pv2 = _import(session, slug, 2)
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
    slug = f"dry-{secrets.token_hex(3)}"
    assignment, _, _ = _setup(session, slug)
    pv1_id = assignment.fixed_pack_version_id
    _import(session, slug, 2)

    migrate_assignment(session, assignment, 2, dry_run=True)

    assert assignment.fixed_pack_version_id == pv1_id


# ── A ref that changes meaning ───────────────────────────────────────────────────────────

def _import_renaming(session, slug, version, ref, display_ref):
    """The same fixture pack, with one document renamed -- the shape an envelope rebuild
    produces, where a ref survives and denotes a different artefact."""
    data = copy.deepcopy(testco_alpha.PACK)
    data["company"]["slug"] = slug
    data["company"]["name"] = slug
    data["version"] = version
    for document in data["documents"]:
        if document["ref"] == ref:
            document["display_ref"] = display_ref
    return import_content(session, schema.load_pack(data), source_sha256=secrets.token_hex(32))


def test_migrate_refused_when_a_used_ref_names_a_different_document(session):
    """The case the gate could not see: nothing is missing, so missing_documents is empty and
    the migration reported feasible while reattaching the student's work."""
    slug = f"ident-{secrets.token_hex(3)}"
    assignment, ws, used_ref = _setup(session, slug)
    _import_renaming(session, slug, 2, used_ref, "Something else entirely")

    report = migrate_assignment(session, assignment, 2)

    assert report.missing_documents == []
    assert [(c.ref, c.field) for c in report.changed_identity] == [(used_ref, "display_ref")]
    assert not report.feasible


def test_the_override_lets_a_deliberate_migration_through(session):
    """A guard with no override makes a considered decision unexecutable, and one that cannot be
    overridden gets deleted by the next person in a hurry."""
    slug = f"ovr-{secrets.token_hex(3)}"
    assignment, ws, used_ref = _setup(session, slug)
    _import_renaming(session, slug, 2, used_ref, "Something else entirely")

    report = migrate_assignment(
        session, assignment, 2, dry_run=False, accept_identity_changes=True
    )

    assert report.applied
    assert report.changed_identity, "the override must still report what it let through"


def test_the_override_does_not_excuse_content_that_is_gone(session):
    """It suppresses the identity block and nothing else."""
    slug = f"gone-{secrets.token_hex(3)}"
    assignment, ws, _ = _setup(session, slug)
    _import(session, slug, 2, drop=USED_ACCOUNT_NUMBER)

    report = migrate_assignment(
        session, assignment, 2, dry_run=False, accept_identity_changes=True
    )

    assert report.missing_accounts == [USED_ACCOUNT_NUMBER]
    assert not report.feasible
    assert not report.applied


def test_an_unchanged_rebuild_reports_no_identity_change(session):
    slug = f"same-{secrets.token_hex(3)}"
    assignment, ws, _ = _setup(session, slug)
    _import(session, slug, 2)

    report = migrate_assignment(session, assignment, 2)

    assert report.changed_identity == []
    assert report.feasible
