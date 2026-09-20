"""Activity the instructor needs and the student never sees (I2.5, T8.7).

A refused save is the most useful thing this app records that paper never could: it says what a
student was attempting when they got stuck, and on which document. It carries the message the
student saw, never their figures, and no personal data reaches the row (D4).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import ActivityEvent, Workspace

REFUSED_SAVE = "save_refused"
VIEW = "view"


def record_refused_save(
    session: Session, workspace: Workspace, document_ref: str | None, reason: str
) -> ActivityEvent:
    """A save the app would not accept: out of balance, no account, a date outside the period."""
    event = ActivityEvent(
        workspace_id=workspace.id,
        kind=REFUSED_SAVE,
        detail={"document": document_ref, "reason": reason},
    )
    session.add(event)
    session.flush()
    return event


def record_view(session: Session, workspace: Workspace, page: str) -> ActivityEvent:
    """A page view, so time spent reading counts towards time on task (T8.7)."""
    event = ActivityEvent(workspace_id=workspace.id, kind=VIEW, detail={"page": page})
    session.add(event)
    session.flush()
    return event
