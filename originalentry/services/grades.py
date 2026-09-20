"""Storing and adjusting marks (I3.1–I3.5, A12).

A run is immutable: regrading writes another run. An override is a separate record with a reason
that must be given, and it is applied **on top of** whatever the latest run says — so an
instructor's judgement is never undone by the next run of the engine.

Points live in hundredths of a point in the database, for the same reason money lives in cents
(D1): a float that drifts by a hundredth is a mark nobody can account for.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..grading.models import GradeResult, result_to_dict
from ..models import Assignment, GradeComment, GradeOverride, GradeRun, Workspace

# How a workspace was handed in, at the moment it was graded (tension 10, I3.8).
OPEN = "open"
SUBMITTED = "submitted"
SUBMITTED_LATE = "submitted_late"
NOT_SUBMITTED = "not_submitted"


def to_hundredths(points: float) -> int:
    return int(round(points * 100))


def from_hundredths(value: int) -> float:
    return value / 100


@dataclass(frozen=True)
class ComponentMark:
    key: str
    label: str
    points: float
    max_points: float
    overridden: bool = False
    reason: str | None = None


@dataclass(frozen=True)
class FinalMarks:
    components: tuple[ComponentMark, ...]
    total_points: float
    max_points: float
    needs_review: bool
    comment: str | None = None
    engine_version: str = ""
    #: What the pack asked to be taken off for a designed error (T8.5). Usually empty.
    deductions: tuple[tuple[str, float], ...] = ()  # (label, points)

    @property
    def deducted_points(self) -> float:
        return sum(points for _, points in self.deductions)

    @property
    def percent(self) -> float:
        return 100 * self.total_points / self.max_points if self.max_points else 0.0


def record_run(
    session: Session, workspace: Workspace, result: GradeResult, created_by=None
) -> GradeRun:
    run = GradeRun(
        workspace_id=workspace.id,
        pack_version_id=workspace.pack_version_id,
        variant_id=workspace.variant_id,
        engine_version=result.engine_version,
        total_points=to_hundredths(result.total_points),
        max_points=to_hundredths(result.max_points),
        needs_review=result.needs_review,
        submission_status=submission_status(session, workspace),
        results=result_to_dict(result),
        created_by_id=created_by.id if created_by is not None else None,
    )
    session.add(run)
    session.flush()
    return run


def latest_run(session: Session, workspace: Workspace) -> GradeRun | None:
    run = session.scalars(
        select(GradeRun)
        .where(GradeRun.workspace_id == workspace.id)
        .order_by(GradeRun.created_at.desc(), GradeRun.id.desc())
        .limit(1)
    ).one_or_none()
    return run


def set_override(
    session: Session,
    workspace: Workspace,
    component_key: str,
    points: float,
    reason: str,
    actor=None,
) -> GradeOverride:
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("An override records why the mark was changed.")

    session.execute(
        update(GradeOverride)
        .where(
            GradeOverride.workspace_id == workspace.id,
            GradeOverride.component_key == component_key,
            GradeOverride.superseded_at.is_(None),
        )
        .values(superseded_at=datetime.now(UTC))
    )
    session.flush()

    override = GradeOverride(
        workspace_id=workspace.id,
        component_key=component_key,
        points=to_hundredths(points),
        reason=reason,
        created_by_id=actor.id if actor is not None else None,
    )
    session.add(override)
    session.flush()
    return override


def active_overrides(session: Session, workspace: Workspace) -> dict[str, GradeOverride]:
    rows = session.scalars(
        select(GradeOverride).where(
            GradeOverride.workspace_id == workspace.id,
            GradeOverride.superseded_at.is_(None),
        )
    )
    return {row.component_key: row for row in rows}


def set_comment(session: Session, workspace: Workspace, body: str, actor=None) -> GradeComment:
    comment = session.get(GradeComment, workspace.id)
    if comment is None:
        comment = GradeComment(workspace_id=workspace.id, body=body)
        session.add(comment)
    comment.body = body
    comment.updated_by_id = actor.id if actor is not None else None
    comment.updated_at = datetime.now(UTC)
    session.flush()
    return comment


def final_marks(session: Session, workspace: Workspace) -> FinalMarks | None:
    """The latest run with every active override applied on top (I3.4)."""
    run = latest_run(session, workspace)
    if run is None:
        return None

    overrides = active_overrides(session, workspace)
    components = []
    for component in run.result.components:
        override = overrides.get(component.key)
        components.append(
            ComponentMark(
                key=component.key,
                label=component.label,
                points=from_hundredths(override.points) if override else component.points,
                max_points=component.max_points,
                overridden=override is not None,
                reason=override.reason if override else None,
            )
        )

    comment = session.get(GradeComment, workspace.id)
    # An override replaces what a component earned; a deduction is not a component and stands
    # outside that, so it applies to the overridden total too. Anything else would let a single
    # override quietly cancel a penalty the pack asked for, without anyone saying so.
    deductions = tuple((d.label, d.points) for d in run.result.deductions)
    earned = sum(c.points for c in components)
    taken = sum(points for _, points in deductions)
    return FinalMarks(
        components=tuple(components),
        total_points=max(0.0, earned - taken),
        max_points=sum(c.max_points for c in components),
        needs_review=any(
            c.needs_review and c.key not in overrides for c in run.result.components
        ) or bool(run.result.review_reasons),
        comment=comment.body if comment else None,
        engine_version=run.engine_version,
        deductions=deductions,
    )


def submission_status(session: Session, workspace: Workspace) -> str:
    """How the work stood when it was graded. Nothing here computes a penalty (tension 10)."""
    if workspace.status == "submitted":
        return SUBMITTED_LATE if (workspace.submitted_late_hours or 0) > 0 else SUBMITTED

    from .accommodations import close_for

    close = close_for(session, workspace)
    if close is not None and datetime.now(UTC) > close:
        return NOT_SUBMITTED  # closed, and never handed in (I3.8)
    return OPEN


def _section_workspaces(session: Session, assignment: Assignment):
    from ..models import Workspace

    return (
        select(Workspace)
        .where(
            Workspace.assignment_id == assignment.id,
            Workspace.archived_at.is_(None),
            # A student still waiting on a hand-assigned variant (I1.3) has been given no
            # figures. Marking them zero out of a hundred would be a lie about work nobody
            # could have done, so they are not gradable until their instructor hands one out.
            Workspace.variant_id.is_not(None),
        )
        .order_by(Workspace.id)
    )


def ungraded_count(session: Session, assignment: Assignment) -> int:
    """How many of this section's workspaces have no run at all yet (T8.6)."""
    from ..models import Workspace

    return session.execute(
        select(func.count())
        .select_from(Workspace)
        .where(
            Workspace.assignment_id == assignment.id,
            Workspace.archived_at.is_(None),
            Workspace.variant_id.is_not(None),
            ~select(GradeRun.id)
            .where(GradeRun.workspace_id == Workspace.id)
            .exists(),
        )
    ).scalar_one()


def grade_section(
    session: Session,
    assignment: Assignment,
    actor=None,
    limit: int | None = None,
    after_id: int | None = None,
):
    """Grade the workspaces of one assignment in id order, and store a run for each.

    ``limit`` caps how many are graded in one call, so a large section is worked through in
    batches that finish well inside the web request limit (T8.6, I3.7). ``after_id`` is where the
    last batch stopped: without it every batch would grade the same first workspaces again, and a
    section larger than one batch could never be finished.

    Returns the runs made, how many workspaces the section holds, and the id to carry into the
    next batch (``None`` when there are no more).
    """
    from ..grading.workspace import grade_workspace
    from ..models import Workspace

    total = session.execute(
        select(func.count()).select_from(_section_workspaces(session, assignment).subquery())
    ).scalar_one()

    query = _section_workspaces(session, assignment)
    if after_id is not None:
        query = query.where(Workspace.id > after_id)
    if limit:
        query = query.limit(limit)

    graded, last_id = [], None
    for workspace in session.scalars(query):
        graded.append(record_run(session, workspace, grade_workspace(session, workspace), actor))
        last_id = workspace.id
    return graded, total, last_id


def release_marks(session: Session, assignment: Assignment, actor=None) -> Assignment:
    """Open the section's marks to its students, in one action (I3.6)."""
    assignment.marks_released_at = datetime.now(UTC)
    session.flush()
    return assignment
