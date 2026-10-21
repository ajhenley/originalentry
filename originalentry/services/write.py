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
from ..decorators import STAFF_ROLES
from ..models import (
    LATE_ACCEPT,
    ROLE_STUDENT,
    ActivityEvent,
    Assignment,
    Workspace,
)
from ..workspaces import is_own_practice
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
    # The one definition of who may write, shared with decorators.workspace_view. This gate and
    # that one must never disagree: relax only the decorator and chapter problems become writable
    # while every write through here is still refused.
    own_practice = is_own_practice(workspace, actor)
    if not own_practice and (actor.role != ROLE_STUDENT or actor.id != workspace.student_id):
        # Staff view is read-only; the write path never runs for them.
        raise WriteRefused(messages.READ_ONLY_SUBMITTED)
    if workspace.status == "submitted":
        # A practice copy is read-only once handed in too: that is part of the experience its
        # owner is checking. Start over is how they get a writable one back.
        raise WriteRefused(messages.READ_ONLY_SUBMITTED)
    if workspace.variant_id is None:
        # A manual-variant assignment the instructor has not handed out yet (I1.3). Their own copy
        # has nothing to work on either.
        raise WriteRefused(messages.WAITING_FOR_VARIANT)
    if own_practice and actor.role in STAFF_ROLES:
        # The deadline is the only gate a practice copy skips, and it has to: a teacher preparing
        # next term's assignment works a copy whose window has not opened, or has long closed.
        #
        # **And it is the only gate that asks whether they are still staff.** ``is_own_practice``
        # carries no role check, deliberately -- it is a leaf module with no application imports
        # and no second opinion about who staff are -- and ``services.practice`` enforces the
        # precondition on every way into *that* module. Neither reaches here: an owner demoted to
        # student after their copy was made still answers True, ``workspace_view`` sets
        # ``is_staff`` False and ``is_owner`` True so nothing is read-only, and the skip below
        # would let them keep writing past ``due_at`` -- the exact bypass the flag's precondition
        # exists to prevent, reached by navigating to books they already have.
        #
        # Asked here because here is where the skip is *granted*. This function already reads
        # ``actor.role`` one gate above, so it adds no new opinion about who is staff, and
        # ``workspaces.py`` stays free of application imports, which is the reason the role check
        # was left out of it. The skip is all that is withdrawn: they fall through to the deadline
        # like any other student working their own books, rather than being locked out of them.
        return
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
