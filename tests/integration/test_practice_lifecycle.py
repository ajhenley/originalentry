"""Opening a practice copy, resuming it, starting over, and the cases that cannot be worked.

A teacher works their own assignment in a private practice copy. This is its lifecycle: an action
opens one, a second click resumes the same copy rather than resetting hours of work, and a
separate action archives it and opens a fresh one. Nothing is ever destroyed, in keeping with how
a student's restart works.

Three things this suite is built to catch, each of which fails silently otherwise:

* **A restart that hands back something unusable.** ``assignments.archive_and_restart`` opens the
  fresh workspace through ``open_workspace``, whose ``Workspace(...)`` carries no
  ``staff_practice`` -- so a teacher who started over would be handed an ordinary workspace that
  is read-only *to them*, with no banner, and the unique index blocking a real copy beside it.
  The recovery path returning something broken is worse than no recovery path.
* **The flag set for somebody who is not staff.** ``is_own_practice`` carries no role check by
  design, so a workspace with ``staff_practice`` set whose ``student_id`` is a student's would let
  that student write past the deadline. This service is the only writer of the flag, so it is the
  only place that relationship can be enforced.
* **A copy that cannot be written to, with nothing on screen to fix it.** A student-choice
  assignment pins no pack version and a manual-variant assignment hands out no variant; the copy
  would exist, refuse every write with ``WAITING_FOR_VARIANT``, and appear on no hand-out screen.
  Refusing with a reason a template can print is the whole of the difference.

A practice copy ignores the prerequisite chain and ``opens_at`` on purpose -- preparing next
term's assignment is the main use -- and each of those tests first asserts that the rule it is
ignoring was really in force, because a test of an ignored rule that was never set proves nothing.
"""

from __future__ import annotations

import ast
import contextlib
import copy
import pathlib
import secrets
from datetime import UTC, date, datetime, timedelta
from typing import NamedTuple

import pytest
from originalentry.models import (
    ROLE_ADMIN,
    ROLE_INSTRUCTOR,
    ROLE_STUDENT,
    Enrollment,
    PackVersion,
    Section,
    SectionStaff,
    StaffAction,
    User,
    Variant,
    Workspace,
)
from originalentry.packs import schema
from originalentry.packs.importer import import_content
from originalentry.services import practice
from originalentry.services.assignments import (
    MANUAL,
    create_assignment,
    open_workspace,
    prerequisite_met,
    variant_for,
)
from originalentry.services.practice import (
    PracticeRefused,
    open_practice,
    practice_copy,
    restart_practice,
)
from originalentry.workspaces import is_own_practice
from sqlalchemy import select

from tests.packs import testco_alpha

pytestmark = pytest.mark.db


# ── the world ──────────────────────────────────────────────────────────────────────────
#
# Every fixture creates everything it later asserts on. The suite runs against a shared
# development branch that holds rows from manual testing, so a fixture that leaned on the database
# being empty -- or on a user it did not create -- would be accidentally sighted rather than blind.


def _pack(session, tag: str):
    """A company of this suite's own, under a slug nothing else in the database can hold."""
    data = copy.deepcopy(testco_alpha.PACK)
    data["company"]["slug"] = f"{tag}-{secrets.token_hex(3)}"
    return import_content(session, schema.load_pack(data), source_sha256=secrets.token_hex(32))


def _user(session, tag: str, role: str) -> User:
    user = User(email=f"{tag}-{secrets.token_hex(4)}@example.edu", role=role,
                given_name="Ada", family_name="Sowande")
    session.add(user)
    session.flush()
    return user


def _only_variant(session, pack_version) -> int:
    return session.scalars(
        select(Variant.id).where(Variant.pack_version_id == pack_version.id)).one()


def _live(session, assignment, user) -> list[Workspace]:
    """Every live workspace this account holds on this assignment, flagged or not."""
    return list(session.scalars(
        select(Workspace)
        .where(
            Workspace.assignment_id == assignment.id,
            Workspace.student_id == user.id,
            Workspace.archived_at.is_(None),
        )
        .order_by(Workspace.id)
    ))


@pytest.fixture
def pack(session):
    return _pack(session, "lifecycle")


@pytest.fixture
def section(session):
    section = Section(name="Sec", join_code=f"L{secrets.token_hex(3).upper()}")
    session.add(section)
    session.flush()
    return section


@pytest.fixture
def teacher(session, section):
    """The instructor who set the assignment, with the SectionStaff row that says they teach it."""
    teacher = _user(session, "prac-teacher", ROLE_INSTRUCTOR)
    session.add(SectionStaff(section_id=section.id, user_id=teacher.id))
    session.flush()
    return teacher


@pytest.fixture
def student(session, section):
    student = _user(session, "prac-student", ROLE_STUDENT)
    session.add(Enrollment(section_id=section.id, user_id=student.id))
    session.flush()
    return student


@pytest.fixture
def assignment(session, section, pack):
    return create_assignment(session, section=section, title="December", pack_version=pack)


@pytest.fixture
def assignment_with_prerequisite(session, section, pack):
    """December, which waits for November. The teacher has handed in neither."""
    november = create_assignment(session, section=section, title="November", pack_version=pack)
    return create_assignment(session, section=section, title="December", pack_version=pack,
                             prerequisite=november)


@pytest.fixture
def future_assignment(session, section, pack):
    return create_assignment(session, section=section, title="Next term", pack_version=pack,
                             opens_at=datetime.now(UTC) + timedelta(days=30))


@pytest.fixture
def variantless_version(session, pack):
    """A version of the same company with no variant row at all.

    Built directly rather than imported, because ``import_content`` always brings a variant with
    it: the shape this fixture needs is one a human reaches by re-pinning an assignment to a
    version whose variants were never imported, and ``variant_for`` then returns None for a reason
    that has nothing to do with the hand-out policy.
    """
    bare = PackVersion(
        content_pack_id=pack.content_pack_id,
        version=pack.version + 1,
        period_start=date(2026, 12, 1),
        period_end=date(2026, 12, 31),
        fiscal_year_end=date(2026, 12, 31),
        accent_hex="#123456",
        monogram="BAR",
        source_sha256=secrets.token_hex(32),
    )
    session.add(bare)
    session.flush()
    assert session.scalars(
        select(Variant.id).where(Variant.pack_version_id == bare.id)).all() == []
    return bare


@pytest.fixture
def manual_assignment(session, section, pack):
    return create_assignment(session, section=section, title="By hand", pack_version=pack,
                             variant_policy=MANUAL)


@pytest.fixture
def choice_assignment(session, section):
    """A student-choice assignment: two companies offered, and no pinned version at all."""
    return create_assignment(session, section=section, title="Choose one",
                             choice_pack_versions=[_pack(session, "choice-a"),
                                                   _pack(session, "choice-b")])


@pytest.fixture
def promoted_user(session, section, assignment):
    """An account that worked this assignment as a student and is staff now.

    The shape behind Review Focus 5: their old workspace is live, unflagged, and already occupies
    the one slot ``uq_workspace_assignment_student_live`` allows for the pair.
    """
    user = _user(session, "prac-promoted", ROLE_STUDENT)
    session.add(Enrollment(section_id=section.id, user_id=user.id))
    session.flush()
    open_workspace(session, assignment, user)
    user.role = ROLE_INSTRUCTOR
    session.add(SectionStaff(section_id=section.id, user_id=user.id))
    session.flush()
    return user


# ── opening and resuming ───────────────────────────────────────────────────────────────

def test_opening_creates_a_practice_copy_pinned_to_the_assignments_version(
    session, teacher, assignment, pack
):
    opened = open_practice(session, assignment, teacher)

    assert opened.staff_practice is True
    assert opened.student_id == teacher.id
    assert opened.pack_version_id == assignment.fixed_pack_version_id
    assert opened.variant_id == _only_variant(session, pack)
    assert opened.archived_at is None
    assert opened.status == "not_started"
    # The two write gates consult exactly this, and nothing else.
    assert is_own_practice(opened, teacher) is True
    found = practice_copy(session, assignment, teacher)
    assert found is not None and found.id == opened.id


def test_opening_again_resumes_the_same_copy(session, teacher, assignment):
    """A practice set takes hours. A second click must not be a reset."""
    first = open_practice(session, assignment, teacher)
    first.status = "in_progress"
    first.started_at = datetime.now(UTC)
    session.flush()

    again = open_practice(session, assignment, teacher)

    assert again.id == first.id
    assert again.status == "in_progress", "a second click reset the copy"
    assert [ws.id for ws in _live(session, assignment, teacher)] == [first.id]


def test_a_copy_is_only_the_owners_own(session, teacher, assignment, section):
    """The flag is set in combination with one person's id, and that person alone owns the copy.

    Task 1's ``is_own_practice`` carries no role check, on the explicit condition that the opener
    ties the flag to the asking account -- so a copy opened for one teacher must be nobody else's,
    and the next test says the same thing about the code that writes it.
    """
    other_teacher = _user(session, "prac-other", ROLE_INSTRUCTOR)
    session.add(SectionStaff(section_id=section.id, user_id=other_teacher.id))
    session.flush()

    opened = open_practice(session, assignment, teacher)

    assert is_own_practice(opened, teacher) is True
    assert is_own_practice(opened, other_teacher) is False
    assert practice_copy(session, assignment, other_teacher) is None


def test_the_opener_is_recorded_in_the_staff_trail(session, teacher, assignment):
    """D2: anything staff do to a workspace is recorded with the ids and no figures."""
    opened = open_practice(session, assignment, teacher)

    recorded = session.scalars(
        select(StaffAction).where(StaffAction.target_table == "workspace",
                                  StaffAction.target_id == opened.id)).all()

    assert [entry.action for entry in recorded] == [practice.OPEN_PRACTICE]
    assert recorded[0].actor_id == teacher.id


def test_the_actor_recorded_can_differ_from_the_owner(session, teacher, assignment, section):
    """``actor`` exists only for the audit entry; owner-only means they are normally the same
    person, so it defaults to the teacher the copy belongs to."""
    admin = _user(session, "prac-admin", ROLE_ADMIN)

    opened = open_practice(session, assignment, teacher, actor=admin)

    recorded = session.scalars(
        select(StaffAction).where(StaffAction.target_table == "workspace",
                                  StaffAction.target_id == opened.id)).one()

    assert opened.student_id == teacher.id, "the copy must belong to the teacher, not the actor"
    assert recorded.actor_id == admin.id


# ── starting over ──────────────────────────────────────────────────────────────────────

def test_restart_archives_the_old_copy_and_opens_a_fresh_one(session, teacher, assignment):
    """Nothing is destroyed, in keeping with how a student's restart works."""
    old = open_practice(session, assignment, teacher)
    old_id = old.id

    fresh = restart_practice(session, assignment, teacher)

    assert fresh.id != old_id
    assert old.archived_at is not None
    assert fresh.archived_at is None
    assert fresh.staff_practice is True, (
        "a fresh copy without the flag is read-only to its owner again -- the recovery path "
        "silently handing back something unusable"
    )
    assert fresh.student_id == teacher.id
    assert is_own_practice(fresh, teacher) is True
    assert fresh.pack_version_id == assignment.fixed_pack_version_id
    assert fresh.variant_id is not None
    # The partial unique index allows one live row per (assignment, student); the archived one
    # does not collide.
    assert [ws.id for ws in _live(session, assignment, teacher)] == [fresh.id]


def test_restart_keeps_the_archived_copy_readable(session, teacher, assignment):
    old = open_practice(session, assignment, teacher)
    old.status = "in_progress"
    session.flush()
    old_id = old.id

    fresh = restart_practice(session, assignment, teacher)

    # Read it back out of the database rather than out of the identity map, which would answer
    # with the object this test already holds.
    session.expire_all()
    kept = session.get(Workspace, old_id)
    assert kept is not None, "the old copy was deleted rather than archived"
    assert kept.archived_at is not None
    assert kept.status == "in_progress", "the work on the old copy was discarded"
    assert kept.staff_practice is True, "the archived copy stopped being the teacher's own"
    assert kept.id != fresh.id


def test_restart_records_which_copy_replaced_which(session, teacher, assignment):
    """How somebody finds the archived copy afterwards -- the shape ``archive_and_restart``
    already writes for a student's restart, so the trail reads the same for both."""
    old = open_practice(session, assignment, teacher)
    old_id = old.id

    fresh = restart_practice(session, assignment, teacher)

    archived = session.scalars(
        select(StaffAction).where(StaffAction.target_table == "workspace",
                                  StaffAction.target_id == old_id,
                                  StaffAction.action == "archive_workspace")).one()

    assert archived.detail.get("restarted_as") == fresh.id
    assert archived.reason, "an archived copy with no reason recorded"


def test_a_refused_restart_leaves_the_copy_live(
    session, teacher, assignment, variantless_version
):
    """The data-loss path, and the reason the order of operations is not a style question.

    ``app._register_audit``'s ``after_request`` hook commits the session on every request by a
    signed-in staff user, so a route that catches ``PracticeRefused`` and flashes ``.reason`` --
    the pattern this refusal design invites -- **commits** whatever the service left behind. A
    restart that archived the old copy before discovering it could not open a replacement would
    destroy a teacher's work, put nothing in its place, and write no audit entry naming it.
    """
    old = open_practice(session, assignment, teacher)
    old_id = old.id
    # Re-pinned to a version with no variant, the way an assignment reaches this between the two
    # clicks: the copy exists and a replacement cannot be opened.
    assignment.fixed_pack_version_id = variantless_version.id
    session.flush()

    with pytest.raises(PracticeRefused) as refused:
        restart_practice(session, assignment, teacher)

    assert refused.value.reason == practice.NO_VARIANT_AT_ALL
    session.expire_all()
    kept = session.get(Workspace, old_id)
    assert kept.archived_at is None, (
        "the copy was archived before the refusal, and the after_request commit would make that "
        "permanent -- the teacher's work gone with nothing to replace it"
    )
    assert [ws.id for ws in _live(session, assignment, teacher)] == [old_id]
    assert session.scalars(
        select(StaffAction).where(StaffAction.target_id == old_id,
                                  StaffAction.action == "archive_workspace")).all() == [], \
        "an archive was recorded for a restart that never happened"


def test_a_restart_by_a_demoted_owner_leaves_the_copy_live(session, teacher, assignment):
    """The same ordering, reached the other way: an owner who is no longer staff.

    Their copy is not theirs to start over, and it is certainly not theirs to lose.
    """
    old = open_practice(session, assignment, teacher)
    old_id = old.id
    teacher.role = ROLE_STUDENT
    session.flush()

    with pytest.raises(practice.PracticeOwnerNotStaff):
        restart_practice(session, assignment, teacher)

    session.expire_all()
    assert session.get(Workspace, old_id).archived_at is None


def test_restart_opens_a_copy_when_there_is_none_yet(session, teacher, assignment):
    """Start over on an assignment with no copy is still a copy, not a crash: the console offers
    both actions and a double click on either must land somewhere usable."""
    fresh = restart_practice(session, assignment, teacher)

    assert fresh.staff_practice is True
    assert [ws.id for ws in _live(session, assignment, teacher)] == [fresh.id]


# ── what a practice copy ignores ───────────────────────────────────────────────────────

def test_a_practice_copy_ignores_the_prerequisite_chain(
    session, teacher, student, assignment_with_prerequisite
):
    """A teacher must not have to work November to practise December."""
    assert prerequisite_met(session, assignment_with_prerequisite, teacher) is False, \
        "the prerequisite was already met, so this test proves nothing"
    assert open_workspace(session, assignment_with_prerequisite, student) is None, \
        "the prerequisite was not actually blocking anybody"

    opened = open_practice(session, assignment_with_prerequisite, teacher)

    assert opened.staff_practice is True
    assert opened.archived_at is None
    assert opened.variant_id is not None


def test_a_practice_copy_ignores_opens_at(session, teacher, future_assignment):
    """Preparing next term's assignment is the main use."""
    assert future_assignment.opens_at > datetime.now(UTC), "the assignment is already open"

    opened = open_practice(session, future_assignment, teacher)

    assert opened.staff_practice is True
    assert opened.variant_id is not None


# ── the refusals ───────────────────────────────────────────────────────────────────────

def test_a_manual_variant_assignment_is_refused_with_a_reason(
    session, teacher, manual_assignment
):
    """Review Focus 3. ``variant_for`` returns None for MANUAL, ``_check_gates`` then refuses
    every write with WAITING_FOR_VARIANT, and the only hand-out UI excludes practice copies -- so
    the copy would be unwritable with nothing on screen to fix it. Refusing says why instead.
    """
    assert variant_for(session, manual_assignment,
                       manual_assignment.fixed_pack_version_id) is None, \
        "the assignment hands out a variant after all, so this test proves nothing"

    with pytest.raises(PracticeRefused) as refused:
        open_practice(session, manual_assignment, teacher)

    # The exact sentence, not merely one with "variant" in it: both variant refusals say that
    # word, so a looser assertion passes with the two sentences swapped -- and the screen then
    # tells a teacher to import a variant when what they have to change is a policy.
    assert refused.value.reason == practice.MANUAL_VARIANT
    assert _live(session, manual_assignment, teacher) == [], \
        "a copy was created and then refused, which is the unusable copy this prevents"
    assert practice_copy(session, manual_assignment, teacher) is None


def test_a_student_choice_assignment_is_refused_with_a_reason(
    session, teacher, choice_assignment
):
    """No single pinned version to copy."""
    assert choice_assignment.fixed_pack_version_id is None, "the assignment pins a version"

    with pytest.raises(PracticeRefused) as refused:
        open_practice(session, choice_assignment, teacher)

    assert "company" in refused.value.reason.lower()
    assert _live(session, choice_assignment, teacher) == []


def test_a_company_with_no_variant_is_refused_with_its_own_reason(
    session, teacher, section, variantless_version
):
    """``variant_for`` returns None two ways, and they are not the same thing to fix: a hand-out
    policy to change, or a variant to import. The screen has to be able to say which."""
    assignment = create_assignment(session, section=section, title="No variants",
                                   pack_version=variantless_version)
    assert assignment.variant_policy != MANUAL, "this would be refused for the other reason"

    with pytest.raises(PracticeRefused) as refused:
        open_practice(session, assignment, teacher)

    assert refused.value.reason == practice.NO_VARIANT_AT_ALL
    assert _live(session, assignment, teacher) == []


def test_an_account_with_its_own_student_workspace_is_refused(
    session, promoted_user, assignment
):
    """Review Focus 5. ``open_workspace`` returns any existing live workspace unchanged, so a
    student later promoted to instructor would be handed their old UNFLAGGED work as "your
    practice copy" -- read-only, no banner, and ``uq_workspace_assignment_student_live`` blocks
    opening a real one beside it. Work done as a student is not converted.
    """
    theirs = _live(session, assignment, promoted_user)
    assert len(theirs) == 1 and theirs[0].staff_practice is False, "the fixture is not that shape"
    student_work_id = theirs[0].id

    with pytest.raises(PracticeRefused) as refused:
        open_practice(session, assignment, promoted_user)
    # And start over must not be the way round it: archiving their student work to make room is
    # exactly the conversion this refusal exists to prevent.
    with pytest.raises(PracticeRefused):
        restart_practice(session, assignment, promoted_user)

    assert refused.value.reason
    session.expire_all()
    still = _live(session, assignment, promoted_user)
    assert [ws.id for ws in still] == [student_work_id], "their student work was replaced"
    assert still[0].staff_practice is False, "work done as a student was converted"
    assert still[0].archived_at is None, "their student work was archived to make room"
    assert practice_copy(session, assignment, promoted_user) is None


def test_a_student_account_is_never_given_the_flag(session, student, assignment):
    """The condition Task 1's reviewer accepted ``is_own_practice``'s missing role check on.

    A workspace with ``staff_practice`` set whose ``student_id`` is a student's skips the deadline
    at both gates. This service is the sole writer of the flag, so nothing else can refuse it.
    """
    with pytest.raises(practice.PracticeOwnerNotStaff):
        open_practice(session, assignment, student)

    assert _live(session, assignment, student) == []
    flagged = session.scalars(
        select(Workspace).where(Workspace.student_id == student.id)).all()
    assert flagged == [], "a student account was handed a workspace by the practice opener"


def test_a_non_staff_owner_is_not_a_refusal_a_route_can_swallow(session, student, assignment):
    """It must not be catchable as ``PracticeRefused``, and that is the whole of the point.

    The other refusals mean "this assignment cannot be practised", which a route prints. This one
    is an invariant breach on the sole writer of a flag that bypasses the deadline, and
    ``except PracticeRefused as e: flash(e.reason)`` would turn it into a message a teacher cannot
    tell from "this assignment is student-choice" -- so a route wired to the wrong user would look
    like a configuration quirk. The house answer for a non-staff account at a staff action is
    ``abort(404)``, which Task 4 can only reach if this escapes the refusal handler.
    """
    assert not issubclass(practice.PracticeOwnerNotStaff, PracticeRefused)

    with pytest.raises(practice.PracticeOwnerNotStaff):
        # The pattern the refusal design invites, written exactly as a route would write it.
        with contextlib.suppress(PracticeRefused):
            open_practice(session, assignment, student)

    # And it does not carry a .reason, so the flash pattern cannot reach for one by accident.
    assert not hasattr(practice.PracticeOwnerNotStaff("x"), "reason")


def test_every_refusal_carries_a_reason_a_screen_can_print(
    session, teacher, section, assignment, manual_assignment, choice_assignment, promoted_user,
    variantless_version
):
    """A refusal a template cannot explain is a dead end.

    Every ``PracticeRefused`` there is, which is every case a screen has to explain; the non-staff
    breach above is deliberately not one of them.
    """
    cases = {
        "a manual-variant assignment": (manual_assignment, teacher),
        "a student-choice assignment": (choice_assignment, teacher),
        "an account that worked it as a student": (assignment, promoted_user),
        "a company with no variant": (
            create_assignment(session, section=section, title="No variants",
                              pack_version=variantless_version),
            teacher,
        ),
    }

    refusals = {}
    for label, (target, asker) in cases.items():
        with pytest.raises(PracticeRefused) as refused:
            open_practice(session, target, asker)
        refusals[label] = refused.value

    unprintable = {
        label: repr(exc.reason) for label, exc in refusals.items()
        if not isinstance(exc.reason, str) or len(exc.reason.split()) < 5
        or not exc.reason.endswith(".") or "{" in exc.reason or "None" in exc.reason
    }
    assert not unprintable, f"refusals a template cannot print: {unprintable}"
    assert all(str(exc) == exc.reason for exc in refusals.values()), \
        "str(exc) and .reason disagree, so a log line and the screen would say different things"
    assert len({exc.reason for exc in refusals.values()}) == len(cases), \
        "two refusals share a reason, so the screen cannot say which of them happened"


# ── the one writer of the flag ─────────────────────────────────────────────────────────

PACKAGE = pathlib.Path(practice.__file__).resolve().parents[1]
FLAG = "staff_practice"


class FlagWrite(NamedTuple):
    """One place a workspace's practice flag could be set, and how it is spelled."""

    module: str
    spelling: str
    function: ast.FunctionDef | ast.AsyncFunctionDef | None
    keywords: dict

    def __str__(self) -> str:
        where = self.function.name if self.function else "<module>"
        return f"{self.module}::{where} ({self.spelling})"


def _flag_writes_in(text: str, *, module: str = "<source>") -> list[FlagWrite]:
    """Every way this source could set ``staff_practice`` on a workspace.

    **Four spellings, because the claim being guarded is "one writer".** The first version of this
    scan collected only ``Workspace(..., staff_practice=True)`` -- the spelling this service
    happens to use -- which is the mistake the chokepoint guard spent four rounds unlearning: a
    scan that sees one spelling reports nothing about the ones it cannot see, and the green test
    then reads as cover. Three others set the same column without a ``Workspace`` keyword:

    * ``workspace.staff_practice = True`` on a row already loaded, which needs no constructor;
    * ``Workspace(**payload)``, which can carry the flag inside a mapping the tree cannot read;
    * ``update(Workspace).values(staff_practice=True)``, which never loads a row at all -- and
      this codebase already writes three ``update(...).values(...)`` statements, so it is the
      house idiom rather than a hypothetical.

    Each is a way a workspace could end up flagged for an account that is not staff, which is a
    deadline bypass at both gates.
    """
    tree = ast.parse(text, filename=module)
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}

    def enclosing(node: ast.AST) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
        current: ast.AST | None = node
        while current is not None:
            if isinstance(current, ast.FunctionDef | ast.AsyncFunctionDef):
                return current
            current = parents.get(current)
        return None

    writes: list[FlagWrite] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            keywords = {kw.arg: kw.value for kw in node.keywords}
            is_workspace = isinstance(node.func, ast.Name) and node.func.id == "Workspace"
            # ``.values(...)`` is matched on the flag alone: this codebase calls it on three other
            # models, so a bare ``**`` there is somebody else's write.
            is_values = isinstance(node.func, ast.Attribute) and node.func.attr == "values"
            if FLAG in keywords and (is_workspace or is_values):
                writes.append(FlagWrite(module, "constructor" if is_workspace else "update",
                                        enclosing(node), keywords))
            elif is_workspace and None in keywords:
                writes.append(FlagWrite(module, "splat", enclosing(node), keywords))
        elif isinstance(node, ast.Assign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(target, ast.Attribute) and target.attr == FLAG
                   for target in targets):
                writes.append(FlagWrite(module, "attribute", enclosing(node), {}))
    return writes


def _flag_writes() -> list[FlagWrite]:
    """The same scan over the whole package.

    Source inspection, in the idiom of ``test_practice_write_gates.py``'s
    ``test_the_rule_is_written_once`` and of the chokepoint guard: what matters is how the write is
    *written*, and no amount of calling this one proves anything about a second one somebody adds
    next year.
    """
    writes = []
    for path in sorted(PACKAGE.rglob("*.py")):
        writes.extend(_flag_writes_in(path.read_text(),
                                      module=path.relative_to(PACKAGE).as_posix()))
    return writes


def test_the_flag_is_only_ever_set_together_with_its_owners_own_id():
    """The flag and the ``student_id`` come from one person, in one function, and cannot diverge.

    This is the structural half of ``test_a_student_account_is_never_given_the_flag``. A function
    taking a flag-bearing owner *and* somebody else's id -- or two person-shaped parameters where
    the id comes from one and the flag is granted on behalf of the other -- is one edit away from
    a workspace that is flagged for a student, which bypasses the deadline at both gates. So the
    writer takes exactly one person besides the session and the assignment, and both halves are
    read off that one name. The audit's ``actor`` is deliberately not a parameter here: it belongs
    to the caller that records the entry, not to the code that sets the flag.
    """
    writes = _flag_writes()
    assert [str(write) for write in writes] == \
        ["services/practice.py::_new_practice_copy (constructor)"], (
        "the practice flag must have exactly one writer, in the service that owns the lifecycle, "
        f"and written as a constructor whose owner can be read off it: {[str(w) for w in writes]}"
    )

    write = writes[0]
    flag = write.keywords[FLAG]
    assert isinstance(flag, ast.Constant) and flag.value is True, (
        f"{write}: staff_practice is set from an expression rather than True, so what it is set "
        "to cannot be read off the code"
    )

    owner = write.keywords.get("student_id")
    assert (isinstance(owner, ast.Attribute) and owner.attr == "id"
            and isinstance(owner.value, ast.Name)), (
        f"{write}: student_id must be read off one named person, so the flag and the id cannot "
        f"come from two different people: {ast.unparse(owner) if owner else None}"
    )

    people = [argument.arg
              for argument in [*write.function.args.args, *write.function.args.kwonlyargs]
              if argument.arg not in ("session", "assignment")]
    assert people == [owner.value.id], (
        f"{write} takes {people}, and sets student_id from {owner.value.id}.id. The one writer "
        "of the flag must take exactly one person, or the flag can be granted for one account "
        "and the id taken from another."
    )


#: Every way somebody would really set the flag. Each of the last three sets the same column
#: without a ``staff_practice`` keyword on a ``Workspace`` constructor, so each was invisible to
#: the first version of this scan.
FLAG_WRITE_SPELLINGS = (
    "ws = Workspace(assignment_id=assignment.id, student_id=teacher.id, staff_practice=True)",
    "workspace.staff_practice = True",
    "found.staff_practice = not found.staff_practice",
    "ws = Workspace(**payload)",
    "session.execute(update(Workspace).values(staff_practice=True))",
    "session.execute(update(Workspace).where(Workspace.id == ws.id)"
    ".values(staff_practice=True))",
)

#: And the mentions that are not writes at all: two reads, the column itself, and the chokepoint's
#: filter -- which is ``workspaces.py``'s business and is guarded over there.
FLAG_INNOCENT_SPELLINGS = (
    'flagged = getattr(workspace, "staff_practice", False)',
    "if workspace.staff_practice:\n    pass",
    "staff_practice: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)",
    "query = select(Workspace).where(Workspace.staff_practice.is_(False))",
    "rows = db.select(Workspace).filter_by(assignment_id=a.id, staff_practice=False)",
    "session.execute(update(Disposition).values(superseded_at=datetime.now(UTC)))",
    "totals = {key: sum(values) for key, values in rows.values()}",
)


def test_the_flag_scan_would_catch_a_write_in_any_of_its_spellings(tmp_path):
    """Guards the guard above, which otherwise cannot fail.

    The claim "one writer" is only worth what the scan can see, and a green scan over a write it
    cannot see is worse than no scan, because nobody looks again.
    """
    for source in FLAG_WRITE_SPELLINGS:
        assert _flag_writes_in(source + "\n"), f"the scan did not catch: {source}"


def test_the_flag_scan_does_not_cry_wolf(tmp_path):
    """The other direction: reading the flag, declaring the column and filtering on it are not
    writes, and reporting them would push somebody into deleting the one legitimate write."""
    for source in FLAG_INNOCENT_SPELLINGS:
        assert not _flag_writes_in(source + "\n"), f"reported as a write: {source}"
