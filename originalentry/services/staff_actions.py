"""The staff audit trail (D2).

Anything an instructor or grader does *to* a student's record is recorded here with the reason
given at the time: reopening a workspace, overriding a mark, releasing a section. It holds ids and
counts, never a name, an email or a figure from anyone's books.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import StaffAction

GRADE_OVERRIDE = "grade_override"
GRADE_COMMENT = "grade_comment"
RELEASE_MARKS = "release_marks"
GRADE_RUN = "grade_run"
REOPEN_WORKSPACE = "reopen_workspace"
STAFF_INVITED = "staff_invited"
STAFF_ROLE_CHANGED = "staff_role_changed"
STAFF_DEACTIVATED = "staff_deactivated"
STAFF_REACTIVATED = "staff_reactivated"
SECTION_STAFF_ADDED = "section_staff_added"
SECTION_STAFF_REMOVED = "section_staff_removed"


def record(
    session: Session,
    actor,
    action: str,
    target_table: str,
    target_id: int,
    reason: str | None = None,
    detail: dict | None = None,
) -> StaffAction:
    entry = StaffAction(
        actor_id=getattr(actor, "id", None),
        action=action,
        target_table=target_table,
        target_id=target_id,
        reason=reason,
        detail=detail or {},
    )
    session.add(entry)
    session.flush()
    return entry
