"""Who may write to a workspace. One definition, consulted by both write gates.

This application has **two** independent write gates, and they must never disagree:

* ``decorators.workspace_view`` sets ``g.read_only``, which the chapter-problem routes and the
  journal screens consult through ``student.views._guard_writable``;
* ``services.write._check_gates`` refuses, inside the single write entry point, any actor who is
  not the owning student -- and every practice-set write (entries, dispositions, posting,
  statements, submit) goes through it.

Relax one and not the other and the feature is half working: chapter problems become writable
while every practice-set write is still refused, with nothing on screen to say which gate said
no. So the rule lives here, in one function, and both gates call it.

**A leaf module, deliberately.** It imports nothing from the application at import time.
``services/write.py`` already defers its ``accommodations`` import to call time to dodge a cycle,
so a home with no app imports at all is the only one that is safe for both callers -- and the
query functions below are imported by seven modules, including ``staff/views.py``, so the module
has to stay cheap to import from anywhere. ``Workspace`` is therefore fetched inside each
function rather than at the top; ``sqlalchemy`` is not the application and is imported normally.

**The read side lives here too**, beside the write rule, for one reason: both are the same
sentence about the same flag. A practice copy is writable by its owner and invisible to the class,
and splitting those two halves across two modules is how one of them gets changed alone.
"""

from __future__ import annotations

from sqlalchemy import select


def is_own_practice(workspace, actor) -> bool:
    """Whether this is ``actor``'s own practice copy -- a workspace they may work as a student.

    A practice copy is an ordinary workspace whose ``staff_practice`` flag is set and whose
    ``student_id`` is the teacher's own id. It is private to its owner: another teacher, a grader
    and an admin are all just staff looking at somebody else's books, and get False.

    **Null-safe on both arguments, and that is load-bearing.** ``app._register_audit`` consults
    this from an ``@app.after_request`` hook that runs for every response, including the many
    requests that never set ``g.workspace``; the hook swallows exceptions because "logging must
    never turn a good response into an error", so an ``AttributeError`` on ``None.staff_practice``
    would not raise -- it would silently stop the durable audit trail recording anything. The
    actor is guarded the same way, for an anonymous caller or one that was never signed in.

    **No role check, and so no answer about one.** This is a leaf module with no application
    imports and no second opinion about who is staff, so the two conditions that depend on a role
    are enforced by the code that acts on this answer, not here: ``services.practice`` refuses to
    *create* a flagged copy for an account that is not staff, on every way into it, and
    ``services.write._check_gates`` refuses the deadline skip to an actor who is not staff at the
    branch where that skip is granted. True here means "this row is this person's own practice
    copy", which stays true of an owner who was demoted yesterday -- and is exactly why neither
    caller may treat it as a permission on its own.
    """
    if workspace is None or actor is None:
        return False
    if not getattr(workspace, "staff_practice", False):
        return False
    return getattr(actor, "id", None) == workspace.student_id


#: Ask across **every** assignment in the install, for the one caller that means it: the console's
#: per-assignment head count, which is a ``group_by`` rather than a filter on one assignment.
#:
#: It exists because the alternative was a default argument, and a default argument made
#: ``class_workspace_clause()`` -- one token from correct, and already in the tree for a reader to
#: copy -- return the practice and archived conditions while silently dropping the assignment. The
#: consequence is not a cosmetic count: a per-assignment screen that lost its assignment filter
#: lists another section's workspaces, which is exactly what ``staff.views._scoped`` and
#: ``decorators.may_see_section`` exist to prevent. Nothing could have noticed, either -- the guard
#: checks that the call is written, not what it was passed. Nobody writes this sentinel by
#: accident, and leaving the argument off is now a ``TypeError``.
ALL_ASSIGNMENTS = object()

#: Said once, because both of the functions that answer about a single assignment say it.
_NOT_ONE_ASSIGNMENT = (
    "ALL_ASSIGNMENTS asks across every assignment in the install; these functions answer about "
    "one. Compose class_workspace_clause(ALL_ASSIGNMENTS) into your own query instead."
)


def _assignment_id(assignment) -> int:
    """The id of an ``Assignment``, or the id itself.

    Both spellings are in the call sites already -- ``assignment.id``, ``found.id`` -- and a
    caller holding only an id should not have to load the row to ask a question about it.
    """
    return getattr(assignment, "id", assignment)


def class_workspace_clause(assignment, *, archived: bool = False) -> tuple:
    """The WHERE criteria for an assignment's **class-facing** workspaces.

    Spread into any query that needs its own joins or extra columns::

        select(Workspace, User).join(User, Workspace.student_id == User.id)
                               .where(*class_workspace_clause(assignment))

    Composing it is the only sanctioned alternative to ``class_workspaces`` below. Writing
    ``Workspace.staff_practice.is_(False)`` into a site by hand is a second copy of this rule, and
    ``tests/guards/test_practice_chokepoint.py`` fails on it: nine sites each remembering the
    condition is not a design, it is nine chances to forget, and a tenth site written next year
    has nobody to remind it.

    ``archived=True`` asks the same question of the archived books (I1.12), which the console's
    archived list needs -- a practice copy that was archived and replaced is still the teacher's,
    and still has no business on a page about the class's books.

    ``assignment`` is required, and the only way to ask across every assignment at once is to
    pass ``ALL_ASSIGNMENTS`` and mean it -- see that constant for why it is a sentinel rather than
    a default. One function either way, so the practice condition still has exactly one home.
    """
    from .models import Workspace

    conditions = [
        Workspace.archived_at.is_not(None) if archived else Workspace.archived_at.is_(None),
        # The whole of the read side of this feature, written once.
        Workspace.staff_practice.is_(False),
    ]
    if assignment is not ALL_ASSIGNMENTS:
        conditions.insert(0, Workspace.assignment_id == _assignment_id(assignment))
    return tuple(conditions)


def class_workspaces(session, assignment, *, archived: bool = False) -> list:
    """The live, non-practice workspaces of one assignment, in id order.

    Every class-level question -- the progress table, the marks export, the cohort diagnostics,
    the mastery report, a grading run, the grading roster, the round-robin count -- is asked
    through this function or through the clause above. A practice copy reaching any one of them
    puts a teacher's own attempts in a student's gradebook, which is the failure this feature is
    designed against: the numbers would simply be wrong, quietly, and an instructor would have no
    reason to disbelieve them.

    Id order, because that is the order every site it replaced already used, and because a grading
    run pages through the section by id (``grades.grade_section``'s ``after_id``).
    """
    from .models import Workspace

    if assignment is ALL_ASSIGNMENTS:
        raise ValueError(_NOT_ONE_ASSIGNMENT)

    return list(
        session.scalars(
            select(Workspace)
            .where(*class_workspace_clause(assignment, archived=archived))
            .order_by(Workspace.id)
        )
    )


def class_workspace_ids(session, assignment, *, archived: bool = False) -> list[int]:
    """The same set, as ids, for a caller that needs them in an ``IN`` clause."""
    from .models import Workspace

    if assignment is ALL_ASSIGNMENTS:
        raise ValueError(_NOT_ONE_ASSIGNMENT)

    return list(
        session.scalars(
            select(Workspace.id)
            .where(*class_workspace_clause(assignment, archived=archived))
            .order_by(Workspace.id)
        )
    )
