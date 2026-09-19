"""The single write entry point for work tables (T3.4).

Every write goes through ``workspace_write``: it locks the workspace row (serialising tabs,
retries and double-clicks), checks the mechanical gates, runs the change, bumps the version,
stamps activity, and commits exactly once. On any exception it rolls back and re-raises — nothing
partial is ever committed. The deferred balance trigger fires at that single commit.

Row locks work through Neon's transaction-mode pooler; session-level advisory locks do not and
are used nowhere (T3.4).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import messages
from ..models import (
    LATE_ACCEPT,
    ROLE_STUDENT,
    ActivityEvent,
    Assignment,
    Workspace,
)
from .errors import WriteRefused


def _now() -> datetime:
    return datetime.now(UTC)


def effective_close(assignment: Assignment) -> datetime | None:
    """When writes stop for a section, before anyone's accommodation is considered.

    Callers that know the student should ask ``accommodations.close_for`` instead: a student with
    extended time is held to their own deadline (I1.11).
    """
    if assignment.late_policy == LATE_ACCEPT and assignment.late_until:
        return assignment.late_until
    return assignment.due_at


def _check_gates(session: Session, workspace: Workspace, actor) -> None:
    if actor.role != ROLE_STUDENT or actor.id != workspace.student_id:
        # Staff view is read-only; the write path never runs for them.
        raise WriteRefused(messages.READ_ONLY_SUBMITTED)
    if workspace.status == "submitted":
        raise WriteRefused(messages.READ_ONLY_SUBMITTED)
    if workspace.variant_id is None:
        raise WriteRefused(messages.READ_ONLY_SUBMITTED)
    # Local import: accommodations reads the write path's own rules, so importing it at module
    # level would be circular.
    from .accommodations import close_for

    close = close_for(session, workspace)
    if close is not None and _now() >= close:
        raise WriteRefused(messages.READ_ONLY_CLOSED)


def workspace_write(
    session: Session,
    workspace_public_id: str,
    actor,
    *,
    activity_kind: str,
    mutate: Callable[[Session, Workspace], object],
    detail: dict | None = None,
):
    """Lock the workspace, gate, run ``mutate(session, workspace)``, stamp activity, commit once.

    ``mutate`` must do all of its work on the passed session and return its result; it must not
    commit. Raises :class:`WriteRefused` for a mechanical refusal.
    """
    try:
        workspace = session.execute(
            select(Workspace)
            .where(Workspace.public_id == workspace_public_id, Workspace.archived_at.is_(None))
            .with_for_update()
        ).scalar_one_or_none()
        if workspace is None:
            raise WriteRefused(messages.READ_ONLY_SUBMITTED)

        _check_gates(session, workspace, actor)
        result = mutate(session, workspace)

        if workspace.status == "not_started":
            workspace.status = "in_progress"
            workspace.started_at = _now()
        workspace.version += 1
        workspace.last_activity_at = _now()
        session.add(
            ActivityEvent(workspace_id=workspace.id, kind=activity_kind, detail=detail or {})
        )
        session.commit()
        return result
    except Exception:
        session.rollback()
        raise
