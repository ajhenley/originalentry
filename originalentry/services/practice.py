"""A teacher's own practice copy: opening it, resuming it, and starting over.

A practice copy is an ordinary workspace whose ``student_id`` is the teacher's own and whose
``staff_practice`` flag is set. ``workspaces.is_own_practice`` is what lets them write to it and
what keeps it out of every class-level number; this module is the only thing that ever *makes*
one, which puts three responsibilities here and nowhere else.

**It does not call ``assignments.open_workspace``.** That function's rules are a student's: the
prerequisite chain, the return-what-exists behaviour, and the student-choice refusal. A practice
copy ignores the prerequisite chain, ``opens_at``, ``due_at`` and the late policy by design --
preparing next term's assignment before it opens is the main use -- so it is built here directly.
It does **not** ignore ``status == "submitted"`` or a missing variant: a submitted copy reads as a
student's does, and start over is how a writable one comes back.

**And it does not call ``assignments.archive_and_restart``.** That function opens the fresh
workspace through ``open_workspace``, whose ``Workspace(...)`` carries no ``staff_practice`` --
so a teacher who started over would be handed an ordinary workspace that is read-only *to them*,
with no banner, and ``uq_workspace_assignment_student_live`` blocking a real copy beside it. The
recovery path silently returning something unusable is worse than having none, and nothing in the
existing suites would have noticed. ``restart_practice`` archives the old copy itself and opens a
fresh *practice* copy, writing the same audit entry the student path writes so the trail reads
alike for both.

**The flag is never set apart from its owner's own id.** ``is_own_practice`` carries no role
check, deliberately -- it is a leaf module with no app imports and no second opinion about who is
staff. The condition on that is enforced here: ``_new_practice_copy`` takes exactly one person
besides the session and the assignment, reads both ``student_id`` and ``staff_practice`` off that
one name, and refuses an account that is not staff. A workspace with ``staff_practice`` set whose
``student_id`` is a student's would let that student write past the deadline at both gates, and
this is the only code that could ever create one.

**Two assignment shapes are refused, with a reason a screen can print.** A student-choice
assignment pins no pack version, and a manual-variant assignment hands out no variant
(``variant_for`` returns None for ``MANUAL``), after which every write is refused with
``messages.WAITING_FOR_VARIANT`` and the only hand-out screen -- ``staff.progress_variant`` --
excludes practice copies. The copy would exist, be unwritable, and have nothing on screen to fix
it. Refusing and saying why is the whole of the difference.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..decorators import STAFF_ROLES
from ..models import Assignment, Workspace
from ..workspaces import is_own_practice
from . import staff_actions
from .assignments import MANUAL, variant_for

#: The audit actions this module records. ``ARCHIVE_WORKSPACE`` is deliberately the same action
#: name ``assignments.archive_and_restart`` writes for a student's restart: the console's archived
#: list and anybody reading the trail should not have to know which kind of restart it was to find
#: the copy that was replaced.
OPEN_PRACTICE = "open_practice"
ARCHIVE_WORKSPACE = "archive_workspace"

#: The reason recorded against the archived copy when a teacher starts over. A reason is required
#: by ``archive_and_restart``'s own signature for a student, and an archived workspace with none
#: recorded is a row nobody can account for later.
RESTART_REASON = "started over on their own practice copy"

# ── the refusals, in the words a screen prints ─────────────────────────────────────────
#
# One sentence saying what happened and one saying what to do about it. A refusal a template
# cannot explain is a dead end: the teacher clicked "work this myself" and nothing happened.

NO_PINNED_VERSION = (
    "This assignment lets each student choose their own company, so there is no one company to "
    "open a practice copy on. Practise it on an assignment that names a single company."
)
MANUAL_VARIANT = (
    "This assignment hands out variants by hand, and the hand-out screen does not list a "
    "practice copy -- so the copy would have no variant to work and no way to be given one. Set "
    "the assignment to hand variants out in turn or at random to practise it."
)
NO_VARIANT_AT_ALL = (
    "This assignment's company has no variant to hand out, so a practice copy would have "
    "nothing in it to work. Import a variant for the company first."
)
WORKED_AS_A_STUDENT = (
    "You already have your own books on this assignment from when you were a student in it. "
    "Work done as a student is not turned into a practice copy, and yours is left as it is."
)
STAFF_ONLY = (
    "A practice copy is for a member of staff working the assignment they set. This account is "
    "a student's on this assignment, and a student works the assignment itself."
)


class PracticeRefused(Exception):
    """A practice copy cannot be opened, with a reason a screen can print.

    ``.reason`` is the whole of the interface: Task 4's routes flash it, and ``str(exc)`` is the
    same sentence so a log line and the screen never say different things. Refusing is the
    deliberate choice over producing a copy that exists and cannot be worked -- an unwritable copy
    with nothing on screen to fix it costs a teacher an afternoon to understand.
    """

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _live_copy(session: Session, assignment: Assignment, owner) -> Workspace | None:
    """The one live workspace this account holds on this assignment -- flagged or not.

    **A per-person lookup, and it must stay one.** It pins ``student_id`` to the single account
    asking, so the only row it can return is that person's own; it is allowlisted in
    ``tests/guards/test_practice_chokepoint.py`` for exactly that reason. Routing it through
    ``class_workspaces`` would be the wrong repair twice over: the chokepoint carries
    ``staff_practice.is_(False)``, so it would hide the very row this function exists to find and
    404 a teacher out of their own copy -- and it would also hide the unflagged student workspace
    that ``open_practice`` has to see in order to refuse.

    Unflagged on purpose. ``uq_workspace_assignment_student_live`` allows one live row per
    (assignment, student), so an account that worked this assignment as a student already occupies
    the slot; asking only about flagged rows would find nothing, create a second, and die on the
    index with a constraint error instead of a sentence.
    """
    return session.scalars(
        select(Workspace).where(
            Workspace.assignment_id == assignment.id,
            Workspace.student_id == owner.id,
            Workspace.archived_at.is_(None),
        )
    ).one_or_none()


def practice_copy(session: Session, assignment: Assignment, teacher) -> Workspace | None:
    """This teacher's live practice copy of this assignment, or None.

    The question the console asks to decide between "work this myself" and "resume". A live
    workspace that is *not* a practice copy is not one of these, and reads as None.
    """
    found = _live_copy(session, assignment, teacher)
    return found if is_own_practice(found, teacher) else None


def _new_practice_copy(session: Session, assignment: Assignment, owner) -> Workspace:
    """Build and flush a fresh practice copy of ``assignment`` belonging to ``owner``.

    The sole writer of ``staff_practice``, and it takes exactly **one** person. Both halves of
    what makes a practice copy somebody's -- the flag and the ``student_id`` -- are read off that
    one name, so there is no signature through which the flag could be granted on one account's
    behalf while the id came from another. The audit's ``actor`` is deliberately not a parameter:
    it belongs to the caller that records the entry, not to the code that sets the flag.

    Pinned to the assignment's own ``fixed_pack_version_id`` with a variant handed out by the
    assignment's own policy, because the point is to work what the class works.
    """
    if getattr(owner, "role", None) not in STAFF_ROLES:
        raise PracticeRefused(STAFF_ONLY)
    if assignment.fixed_pack_version_id is None:
        raise PracticeRefused(NO_PINNED_VERSION)

    variant_id = variant_for(session, assignment, assignment.fixed_pack_version_id)
    if variant_id is None:
        # Both ways a copy would be unwritable with nothing on screen to fix it, told apart so the
        # screen can say which one happened: a policy to change, or a variant to import.
        raise PracticeRefused(
            MANUAL_VARIANT if assignment.variant_policy == MANUAL else NO_VARIANT_AT_ALL
        )

    workspace = Workspace(
        assignment_id=assignment.id,
        student_id=owner.id,
        staff_practice=True,
        pack_version_id=assignment.fixed_pack_version_id,
        variant_id=variant_id,
        status="not_started",
    )
    session.add(workspace)
    session.flush()
    return workspace


def open_practice(session: Session, assignment: Assignment, teacher, *, actor=None) -> Workspace:
    """Open this teacher's practice copy of ``assignment``, or resume the one they have.

    A practice set takes hours, so a second click resumes: the existing copy is returned exactly
    as it stands, never reset. Starting over is a separate, explicitly-labelled action.

    ``actor`` is for the audit entry alone and defaults to ``teacher``, because owner-only means
    they are normally the same person; the copy always belongs to ``teacher``, whoever asked.

    Raises ``PracticeRefused`` -- with a ``.reason`` a screen can print -- for an assignment no
    practice copy can be made of, and for an account whose live workspace on this assignment is
    their own student work.
    """
    existing = _live_copy(session, assignment, teacher)
    if existing is not None:
        if not is_own_practice(existing, teacher):
            # Their own work, done as a student, sitting in the one live slot the index allows.
            # Handing it back as "your practice copy" would be read-only with no banner, and
            # converting it would rewrite work that was marked as a student's.
            raise PracticeRefused(WORKED_AS_A_STUDENT)
        return existing

    opened = _new_practice_copy(session, assignment, teacher)
    _record_open(session, actor if actor is not None else teacher, assignment, opened)
    return opened


def restart_practice(session: Session, assignment: Assignment, teacher, *,
                     actor=None) -> Workspace:
    """Archive this teacher's practice copy and open a fresh one.

    Nothing is destroyed, in keeping with how a student's restart works: the old copy stays,
    archived, readable and still flagged as the teacher's own. The fresh one is a **practice**
    copy -- see this module's docstring for why delegating to ``assignments.archive_and_restart``
    would hand back an ordinary workspace its owner cannot write to.

    Start over with no copy yet simply opens one: the console offers both actions beside each
    other, and either click has to land somewhere usable.
    """
    actor = actor if actor is not None else teacher
    existing = _live_copy(session, assignment, teacher)
    if existing is not None and not is_own_practice(existing, teacher):
        # Start over must not be the way round the refusal above: archiving work done as a student
        # to make room for a practice copy is exactly the conversion that refusal prevents.
        raise PracticeRefused(WORKED_AS_A_STUDENT)

    if existing is not None:
        # Archived, and flushed, before the insert: uq_workspace_assignment_student_live allows
        # one live row per (assignment, student) and the archived one no longer collides.
        existing.archived_at = datetime.now(UTC)
        session.flush()

    fresh = _new_practice_copy(session, assignment, teacher)
    if existing is not None:
        staff_actions.record(
            session, actor, ARCHIVE_WORKSPACE, "workspace", existing.id,
            reason=RESTART_REASON, detail={"restarted_as": fresh.id},
        )
    _record_open(session, actor, assignment, fresh)
    return fresh


def _record_open(session: Session, actor, assignment: Assignment, workspace: Workspace) -> None:
    """One audit entry per copy created (D2): ids and the assignment, never a figure or a name."""
    staff_actions.record(
        session, actor, OPEN_PRACTICE, "workspace", workspace.id,
        detail={"assignment_id": assignment.id, "student_id": workspace.student_id},
    )
