"""Submission, and giving it back. Marks a workspace submitted and stamps how late it was; the
app computes no penalty (tension 10). After this the write path refuses further writes.

Reopening (S6.5) undoes that, because handing in is a button a tired student can press with an
adjustment still to make. It is a staff action with a reason, and it never erases the fact that
they submitted or when — that is what the mark was taken on."""

from __future__ import annotations

import math
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from .. import messages
from ..models import Assignment, Workspace
from . import staff_actions
from .errors import WriteRefused
from .write import effective_close


def submit_workspace(session: Session, workspace: Workspace) -> Workspace:
    if workspace.status == "submitted":
        raise WriteRefused(messages.READ_ONLY_SUBMITTED)

    now = datetime.now(UTC)
    assignment = session.get(Assignment, workspace.assignment_id)
    due = effective_close(assignment) if assignment else None
    late_hours = 0
    if due is not None and now > due:
        late_hours = math.ceil((now - due).total_seconds() / 3600)

    workspace.status = "submitted"
    workspace.submitted_at = now
    workspace.submitted_late_hours = late_hours
    return workspace


class ReopenRefused(Exception):
    """Reopening would not actually let the student work. Mechanical, like every refusal here."""


NOTHING_TO_REOPEN = "This workspace was not handed in, so there is nothing to give back."
NEEDS_A_DATE = (
    "This assignment's deadline has already passed, so reopening on its own would leave them "
    "still unable to write. Give the date and time they should work until."
)


def reopen_workspace(
    session: Session, workspace: Workspace, *, reason: str, until: datetime | None = None,
    actor=None,
) -> Workspace:
    """Give a submitted workspace back to the student (S6.5).

    ``until`` is that student's new deadline. It is required when the assignment has already
    closed, because the write path refuses on the deadline whatever the status says — a reopen
    that left them still unable to write would be worse than a refusal that explains itself.
    """
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("Reopening records why the work was given back.")
    if workspace.status != "submitted":
        raise ReopenRefused(NOTHING_TO_REOPEN)

    from .accommodations import close_for, set_accommodation

    now = datetime.now(UTC)
    if until is None and (close := close_for(session, workspace)) is not None and now >= close:
        raise ReopenRefused(NEEDS_A_DATE)

    if until is not None:
        # Their own deadline, through the machinery that already exists for one student's
        # deadline (I1.11), so there is still one answer to "when does this student's work stop".
        from ..models import Assignment, User

        set_accommodation(
            session,
            assignment=session.get(Assignment, workspace.assignment_id),
            student=session.get(User, workspace.student_id),
            due_at=until,
            late_until=until,
            reason=reason,
            actor=actor,
        )

    workspace.status = "in_progress"
    workspace.reopened_at = now
    # submitted_at and submitted_late_hours stay: that they handed in, and when, is the record
    # the mark was taken on. Handing in again overwrites them with what happened then.
    session.flush()
    staff_actions.record(
        session, actor, staff_actions.REOPEN_WORKSPACE, "workspace", workspace.id,
        reason=reason, detail={"until": until.isoformat() if until else None},
    )
    return workspace
