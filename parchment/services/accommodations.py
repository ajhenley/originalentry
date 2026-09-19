"""Per-student accommodations (I1.11).

The deadline a student is held to is *their* deadline: the section's, unless the instructor has
given them another. Everything that asks when writing stops — the write path, grading's view of
how the work was handed in, the Progress screen — asks :func:`close_for`, so there is one answer
and no screen can drift from it.

Extended time is not a favour. For some students it is the difference between being able to sit
the assignment and not, which is why it is recorded with the reason given at the time and why
withdrawing one leaves the record behind.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..models import Assignment, AssignmentOverride, Workspace
from ..models.work import LATE_ACCEPT
from . import staff_actions


def current_override(
    session: Session, assignment_id: int, user_id: int
) -> AssignmentOverride | None:
    return session.scalars(
        select(AssignmentOverride).where(
            AssignmentOverride.assignment_id == assignment_id,
            AssignmentOverride.user_id == user_id,
            AssignmentOverride.withdrawn_at.is_(None),
        )
    ).one_or_none()


def close_for(session: Session, workspace: Workspace) -> datetime | None:
    """When writing stops for this student. The one place that decides it."""
    assignment = session.get(Assignment, workspace.assignment_id)
    if assignment is None:
        return None

    override = current_override(session, assignment.id, workspace.student_id)
    accepts_late = assignment.late_policy == LATE_ACCEPT

    if override is not None:
        if accepts_late and override.late_until:
            return override.late_until
        if override.due_at:
            return override.due_at

    if accepts_late and assignment.late_until:
        return assignment.late_until
    return assignment.due_at


def overrides_for(session: Session, assignment: Assignment) -> dict[int, AssignmentOverride]:
    """Live accommodations for one assignment, by student id — one query for a whole section."""
    rows = session.scalars(
        select(AssignmentOverride).where(
            AssignmentOverride.assignment_id == assignment.id,
            AssignmentOverride.withdrawn_at.is_(None),
        )
    )
    return {row.user_id: row for row in rows}


def set_accommodation(
    session: Session,
    *,
    assignment: Assignment,
    student,
    due_at: datetime | None = None,
    late_until: datetime | None = None,
    checkpoint_extension_hours: int | None = None,
    reason: str,
    actor=None,
) -> AssignmentOverride:
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("An accommodation records why it was given.")

    session.execute(
        update(AssignmentOverride)
        .where(
            AssignmentOverride.assignment_id == assignment.id,
            AssignmentOverride.user_id == student.id,
            AssignmentOverride.withdrawn_at.is_(None),
        )
        .values(withdrawn_at=datetime.now(UTC))
    )
    session.flush()

    override = AssignmentOverride(
        assignment_id=assignment.id,
        user_id=student.id,
        due_at=due_at,
        late_until=late_until,
        checkpoint_extension_hours=checkpoint_extension_hours,
        reason=reason,
        created_by_id=getattr(actor, "id", None),
    )
    session.add(override)
    session.flush()
    staff_actions.record(
        session, actor, "set_accommodation", "assignment", assignment.id, reason=reason,
        detail={"student": student.public_id, "due_at": due_at.isoformat() if due_at else None,
                "late_until": late_until.isoformat() if late_until else None},
    )
    return override


def clear_accommodation(
    session: Session, *, assignment: Assignment, student, reason: str, actor=None
) -> None:
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("Withdrawing an accommodation records why.")

    session.execute(
        update(AssignmentOverride)
        .where(
            AssignmentOverride.assignment_id == assignment.id,
            AssignmentOverride.user_id == student.id,
            AssignmentOverride.withdrawn_at.is_(None),
        )
        .values(withdrawn_at=datetime.now(UTC))
    )
    session.flush()
    staff_actions.record(
        session, actor, "clear_accommodation", "assignment", assignment.id, reason=reason,
        detail={"student": student.public_id},
    )
