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
import copy
import pathlib
import secrets
from datetime import UTC, datetime, timedelta

import pytest
from originalentry.models import (
    ROLE_ADMIN,
    ROLE_INSTRUCTOR,
    ROLE_STUDENT,
    Enrollment,
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

    assert "variant" in refused.value.reason.lower()
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
    with pytest.raises(PracticeRefused) as refused:
        open_practice(session, assignment, student)

    assert refused.value.reason
    assert _live(session, assignment, student) == []
    flagged = session.scalars(
        select(Workspace).where(Workspace.student_id == student.id)).all()
    assert flagged == [], "a student account was handed a workspace by the practice opener"


def test_every_refusal_carries_a_reason_a_screen_can_print(
    session, teacher, student, assignment, manual_assignment, choice_assignment, promoted_user
):
    """A refusal a template cannot explain is a dead end."""
    cases = {
        "a manual-variant assignment": (manual_assignment, teacher),
        "a student-choice assignment": (choice_assignment, teacher),
        "an account that worked it as a student": (assignment, promoted_user),
        "a student account": (assignment, student),
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


def _flag_writers() -> list[tuple[str, ast.FunctionDef | None, dict]]:
    """Every ``Workspace(...)`` in the package that carries ``staff_practice``.

    Source inspection, in the idiom of ``test_practice_write_gates.py``'s
    ``test_the_rule_is_written_once`` and of the chokepoint guard: what matters is how the
    constructor is *written*, and no amount of calling this one proves anything about a second one
    somebody adds next year.
    """
    writers = []
    for path in sorted(PACKAGE.rglob("*.py")):
        text = path.read_text()
        tree = ast.parse(text, filename=str(path))
        parents = {child: node for node in ast.walk(tree)
                   for child in ast.iter_child_nodes(node)}
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "Workspace"):
                continue
            keywords = {kw.arg: kw.value for kw in node.keywords if kw.arg}
            if "staff_practice" not in keywords:
                continue
            enclosing, current = None, node
            while current is not None:
                if isinstance(current, ast.FunctionDef | ast.AsyncFunctionDef):
                    enclosing = current
                    break
                current = parents.get(current)
            writers.append((path.relative_to(PACKAGE).as_posix(), enclosing, keywords))
    return writers


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
    writers = _flag_writers()
    assert [module for module, _, _ in writers] == ["services/practice.py"], (
        "the practice flag must have exactly one writer, in the service that owns the lifecycle: "
        f"{[module for module, _, _ in writers]}"
    )

    module, enclosing, keywords = writers[0]
    assert enclosing is not None, f"{module}: the flag is set outside any function"

    flag = keywords["staff_practice"]
    assert isinstance(flag, ast.Constant) and flag.value is True, (
        f"{module}::{enclosing.name}: staff_practice is set from an expression rather than True, "
        "so what it is set to cannot be read off the code"
    )

    owner = keywords.get("student_id")
    assert (isinstance(owner, ast.Attribute) and owner.attr == "id"
            and isinstance(owner.value, ast.Name)), (
        f"{module}::{enclosing.name}: student_id must be read off one named person, so the flag "
        f"and the id cannot come from two different people: {ast.unparse(owner) if owner else None}"
    )

    people = [argument.arg
              for argument in [*enclosing.args.args, *enclosing.args.kwonlyargs]
              if argument.arg not in ("session", "assignment")]
    assert people == [owner.value.id], (
        f"{module}::{enclosing.name} takes {people}, and sets student_id from "
        f"{owner.value.id}.id. The one writer of the flag must take exactly one person, or the "
        "flag can be granted for one account and the id taken from another."
    )
