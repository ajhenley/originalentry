"""What a pack migration does with a teacher's own practice copy: it archives it.

A migration is not a report, which is why it is not the chokepoint's business. It *transforms*,
and the three things it could do with a practice copy are not equivalent:

* **Migrate it with the class.** Then the teacher's throwaway work is part of the feasibility
  union -- ``missing_accounts``, ``missing_parties``, ``missing_documents``,
  ``missing_variants``, ``changed_identity`` -- and one practice entry referencing an account the
  new version drops refuses the whole section's migration. Nothing on screen would say that the
  blocking work was the teacher's own.
* **Leave it behind.** Then the copy sits live, pinned to a version no student has, and the
  teacher carries on practising content the class no longer holds.
* **Archive it.** Nothing is destroyed, the copy stays readable on the version it was worked on,
  the unique index's live slot is freed, and the teacher opens a fresh copy on the new version.
  That is the owner's decision, and this file is what holds it in place.

``services/purge.py`` is the other write path that must not exclude practice copies, and it is
deliberately untouched by this work: retention deletion has to reach every row or it orphans
records behind foreign keys. Its tests are ``tests/integration/test_purge.py``.

Every fixture creates everything it later asserts on, under a company slug nothing else in the
database can hold. The suite runs against a shared development branch that holds rows from
earlier manual testing, so a fixture leaning on the database being empty -- or on a row it did
not create -- would be accidentally sighted rather than blind.
"""

from __future__ import annotations

import copy
import secrets
from datetime import date

import pytest
from originalentry.models import (
    ROLE_INSTRUCTOR,
    ROLE_STUDENT,
    Account,
    EntryLine,
    JournalEntry,
    Section,
    SectionStaff,
    SourceDocument,
    StaffAction,
    User,
)
from originalentry.packs import schema
from originalentry.packs.importer import import_content
from originalentry.packs.migrate import migrate_assignment
from originalentry.services.assignments import create_assignment, open_workspace
from originalentry.services.practice import open_practice, practice_copy
from sqlalchemy import select

from tests.packs import testco_alpha

pytestmark = pytest.mark.db

#: The account only the teacher's practice entry uses. Dropped from version 2 by the infeasibility
#: test, which is the whole reason the practice copy's entry uses an account of its own: with the
#: teacher and the student on the same accounts, "the practice copy did not block the migration"
#: could not be told from "nothing was missing in the first place".
PRACTICE_ONLY_ACCOUNT = "611"
#: The accounts the student's entry uses. Kept by every version this file imports, except where a
#: test drops one on purpose to see a refusal.
STUDENT_DEBIT_ACCOUNT = "112"
STUDENT_CREDIT_ACCOUNT = "401"
#: The second account the practice entry uses, so its entry balances the way a real one does.
PRACTICE_CASH_ACCOUNT = "101"

ARCHIVE_WORKSPACE = "archive_workspace"


def _import(session, slug: str, version: int, drop: str | None = None):
    """Version ``version`` of this suite's own company, optionally without one account."""
    data = copy.deepcopy(testco_alpha.PACK)
    data["company"]["slug"] = slug
    data["company"]["name"] = slug
    data["version"] = version
    if drop:
        data["accounts"] = [a for a in data["accounts"] if a["number"] != drop]
    return import_content(session, schema.load_pack(data), source_sha256=secrets.token_hex(32))


def _accounts(session, pack_version) -> dict[str, int]:
    return {
        row.number: row.id
        for row in session.scalars(
            select(Account).where(Account.pack_version_id == pack_version.id))
    }


def _entry(session, workspace, pack_version, ref: str, lines, client_key: str) -> JournalEntry:
    """One posted entry in ``workspace``, against a document and accounts it really holds."""
    document_id = session.scalars(
        select(SourceDocument.id).where(SourceDocument.pack_version_id == pack_version.id,
                                        SourceDocument.ref == ref)
    ).one()
    accounts = _accounts(session, pack_version)
    entry = JournalEntry(workspace_id=workspace.id, pack_version_id=pack_version.id,
                         journal_key="general", entry_date=date(2026, 12, 2), kind="regular",
                         client_key=client_key, document_id=document_id)
    session.add(entry)
    session.flush()
    session.add_all([
        EntryLine(entry_id=entry.id, workspace_id=workspace.id,
                  pack_version_id=pack_version.id, line_no=line_no, account_id=accounts[number],
                  debit_cents=debit, credit_cents=credit)
        for line_no, (number, debit, credit) in enumerate(lines, start=1)
    ])
    session.flush()
    return entry


def _lines_of(session, workspace) -> list[EntryLine]:
    return list(session.scalars(
        select(EntryLine).where(EntryLine.workspace_id == workspace.id)
        .order_by(EntryLine.id)))


def _archive_actions(session, workspace) -> list[StaffAction]:
    return list(session.scalars(
        select(StaffAction).where(StaffAction.action == ARCHIVE_WORKSPACE,
                                  StaffAction.target_table == "workspace",
                                  StaffAction.target_id == workspace.id)))


@pytest.fixture
def world(session):
    """One assignment on version 1, with a student's books and the teacher's practice copy.

    Both have work in them, and on **different** accounts: the student's entry uses accounts every
    version here keeps, and the practice entry uses ``PRACTICE_ONLY_ACCOUNT``, which is the one a
    later version drops. That separation is what lets a test say the practice copy did not block
    the class rather than merely that the class was never blocked.

    The practice copy is made by ``services.practice.open_practice`` rather than by a
    ``Workspace(...)`` here, so these tests assert on the shape the service really makes -- it is
    the sole writer of ``staff_practice``, and this suite writes the flag nowhere.
    """
    slug = f"pmig-{secrets.token_hex(3)}"
    pv1 = _import(session, slug, 1)
    section = Section(name=slug, join_code=f"P{secrets.token_hex(3).upper()}")
    teacher = User(email=f"pmig-teacher-{secrets.token_hex(3)}@example.edu",
                   role=ROLE_INSTRUCTOR, given_name="Ada", family_name="Teacherson")
    student = User(email=f"pmig-student-{secrets.token_hex(3)}@example.edu",
                   role=ROLE_STUDENT, given_name="Ivo", family_name="Studentson")
    session.add_all([section, teacher, student])
    session.flush()
    session.add(SectionStaff(section_id=section.id, user_id=teacher.id))
    assignment = create_assignment(session, section=section, title="December", pack_version=pv1)

    student_workspace = open_workspace(session, assignment, student)
    _entry(session, student_workspace, pv1, "INV-1",
           [(STUDENT_DEBIT_ACCOUNT, 10000, 0), (STUDENT_CREDIT_ACCOUNT, 0, 10000)], "s1")

    practice = open_practice(session, assignment, teacher)
    _entry(session, practice, pv1, "INV-2",
           [(PRACTICE_ONLY_ACCOUNT, 2500, 0), (PRACTICE_CASH_ACCOUNT, 0, 2500)], "p1")
    session.flush()
    return {
        "slug": slug, "pv1": pv1, "section": section, "assignment": assignment,
        "teacher": teacher, "student": student, "student_workspace": student_workspace,
        "practice": practice,
    }


# ── the decision ───────────────────────────────────────────────────────────────────────

def test_a_migration_archives_a_practice_copy(session, world):
    """The owner decision: their throwaway work can never make a class-wide migration
    infeasible, and the copy can never sit on a version no student has."""
    pv2 = _import(session, world["slug"], 2)
    practice = world["practice"]
    assert practice.archived_at is None, "the fixture handed over an archived copy"

    report = migrate_assignment(session, world["assignment"], 2, dry_run=False)

    assert report.applied
    session.refresh(practice)
    assert practice.archived_at is not None, "the practice copy was left live on a dead version"
    assert practice.pack_version_id == world["pv1"].id, \
        "the practice copy was migrated with the class instead of being archived"
    assert practice.staff_practice is True, "the archived copy stopped being the teacher's own"
    # Its work stays where it was worked, so the archived copy still reads.
    assert {line.pack_version_id for line in _lines_of(session, practice)} == {world["pv1"].id}
    # And it is counted as what it is: archived, not migrated.
    assert report.workspaces == 1, "the practice copy was counted among the workspaces that moved"
    assert report.practice_archived == 1
    assert pv2.id != world["pv1"].id


def test_the_archive_is_recorded_against_the_copy_it_archived(session, world):
    """An archived workspace nobody can account for later is the failure every other archive path
    in this codebase already guards against -- both of them record ``archive_workspace`` with a
    reason, and a migration that silently archived a teacher's afternoon would be the one path
    with nothing to read."""
    _import(session, world["slug"], 2)
    assert _archive_actions(session, world["practice"]) == [], "the fixture recorded one already"

    migrate_assignment(session, world["assignment"], 2, dry_run=False)

    recorded = _archive_actions(session, world["practice"])
    assert len(recorded) == 1, f"{len(recorded)} archive entries for one copy"
    assert recorded[0].reason, "the archive was recorded with no reason"
    assert recorded[0].detail.get("to_version") == 2
    # The student's workspace was migrated, not archived: nothing may be recorded against it.
    assert _archive_actions(session, world["student_workspace"]) == []


def test_a_practice_copys_entries_do_not_make_a_migration_infeasible(session, world):
    """The reason for it. migrate walks workspaces for missing_accounts, missing_parties,
    missing_documents, missing_variants and changed_identity; a throwaway entry referencing an
    account the new version drops would block the whole section."""
    pv2 = _import(session, world["slug"], 2, drop=PRACTICE_ONLY_ACCOUNT)

    # The premise, asserted rather than assumed: the practice copy really does use that account,
    # and version 2 really has not got it. Either half false and this test would pass vacuously.
    practice_accounts = {line.account_id for line in _lines_of(session, world["practice"])}
    assert _accounts(session, world["pv1"])[PRACTICE_ONLY_ACCOUNT] in practice_accounts
    assert PRACTICE_ONLY_ACCOUNT not in _accounts(session, pv2)

    report = migrate_assignment(session, world["assignment"], 2, dry_run=True)

    assert report.missing_accounts == [], \
        "the teacher's own practice work refused the whole section's migration"
    assert report.feasible


def test_the_students_workspaces_still_migrate(session, world):
    pv2 = _import(session, world["slug"], 2)
    student_workspace = world["student_workspace"]

    migrate_assignment(session, world["assignment"], 2, dry_run=False)

    session.refresh(student_workspace)
    assert student_workspace.archived_at is None, "a student's books were archived"
    assert student_workspace.pack_version_id == pv2.id
    v2_accounts = set(_accounts(session, pv2).values())
    lines = _lines_of(session, student_workspace)
    assert lines, "the fixture posted no lines, so this proves nothing"
    for line in lines:
        assert line.pack_version_id == pv2.id
        assert line.account_id in v2_accounts
    assert world["assignment"].fixed_pack_version_id == pv2.id


def test_the_teacher_can_open_a_fresh_copy_on_the_new_version(session, world):
    pv2 = _import(session, world["slug"], 2)
    migrate_assignment(session, world["assignment"], 2, dry_run=False)

    fresh = open_practice(session, world["assignment"], world["teacher"])

    assert fresh.id != world["practice"].id, "the archived copy was handed back"
    assert fresh.pack_version_id == pv2.id
    assert fresh.staff_practice is True
    assert fresh.archived_at is None
    # And it is the copy the console will find, which is what proves the live slot was freed:
    # uq_workspace_assignment_student_live allows one live row per (assignment, student).
    found = practice_copy(session, world["assignment"], world["teacher"])
    assert found is not None and found.id == fresh.id


def test_a_dry_run_archives_nothing(session, world):
    """migrate_assignment defaults to dry_run=True and must stay side-effect free."""
    _import(session, world["slug"], 2)
    practice = world["practice"]

    report = migrate_assignment(session, world["assignment"], 2)

    assert not report.applied
    assert report.practice_archived == 1, "a dry run must still say what it would archive"
    session.refresh(practice)
    assert practice.archived_at is None, "a dry run archived the teacher's copy"
    assert practice.pack_version_id == world["pv1"].id
    assert _archive_actions(session, practice) == []
    assert world["assignment"].fixed_pack_version_id == world["pv1"].id


def test_a_refused_migration_archives_nothing(session, world):
    """The shape this branch has already paid for once: a refusal discovered *after* something was
    destroyed. An infeasible migration changes nothing at all, so the copy a teacher could not
    have replaced is still there when the operator fixes the pack and runs it again.
    """
    _import(session, world["slug"], 2, drop=STUDENT_CREDIT_ACCOUNT)
    practice = world["practice"]

    report = migrate_assignment(session, world["assignment"], 2, dry_run=False)

    assert not report.feasible and not report.applied
    assert STUDENT_CREDIT_ACCOUNT in report.missing_accounts
    session.refresh(practice)
    assert practice.archived_at is None, \
        "a migration that refused to run archived the teacher's copy on the way out"
    assert _archive_actions(session, practice) == []
    assert world["assignment"].fixed_pack_version_id == world["pv1"].id


def test_an_assignment_whose_only_live_workspace_is_a_practice_copy_still_archives_it(
    session, world
):
    """The branch with nothing to remap takes an early return of its own -- it moves the
    assignment and skips the rest -- and an assignment nobody has joined yet is the ordinary case
    for a teacher preparing next term, not an edge one. Archived there too, or the copy is left
    live on a version the assignment has just left.
    """
    assignment = create_assignment(session, section=world["section"], title="November",
                                   pack_version=world["pv1"])
    alone = open_practice(session, assignment, world["teacher"])
    session.flush()
    pv2 = _import(session, world["slug"], 2)

    report = migrate_assignment(session, assignment, 2, dry_run=False)

    assert report.applied and report.workspaces == 0
    assert report.practice_archived == 1
    session.refresh(alone)
    assert alone.archived_at is not None, \
        "the only copy on the assignment was left live on the version it just left"
    assert assignment.fixed_pack_version_id == pv2.id
    assert len(_archive_actions(session, alone)) == 1
