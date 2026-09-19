"""What an instructor decided about a pack's checkpoints (I1.2, S6.3).

A checkpoint is a numeric self-check standing in front of work that depends on it. An instructor
can put a deadline on one, and can require it to be passed before a later stage — so a student
cannot spend four hours adjusting a trial balance that never agreed.

Both are the instructor's option. An assignment with no rules set behaves exactly as it did
before: nothing is gated and nothing closes.

The refusal these produce is mechanical, like every other refusal in this app. It says which
checkpoint stands in the way, and never whether any figure was any good.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import messages
from ..models import Assignment, AssignmentCheckpoint, PackVersion, Workspace
from . import staff_actions
from .accommodations import current_override
from .checkpoints import checkpoint_state

ADJUSTING = "adjusting"
STATEMENTS = "statements"
CLOSING = "closing"
STAGES = (ADJUSTING, STATEMENTS, CLOSING)

# What a student is told the stage is, in the words they see on their own screens.
STAGE_LABELS = {
    ADJUSTING: "adjusting entries",
    STATEMENTS: "statements",
    CLOSING: "closing entries",
}


def set_checkpoint_rule(
    session: Session,
    *,
    assignment: Assignment,
    ordinal: int,
    deadline_at: datetime | None = None,
    gates_stage: str | None = None,
    actor=None,
) -> AssignmentCheckpoint:
    """Set (or replace) the deadline and gate for one checkpoint of an assignment."""
    if gates_stage not in (None, *STAGES):
        raise ValueError(f"A checkpoint can stand in front of {', '.join(STAGES)}.")

    rule = session.scalars(
        select(AssignmentCheckpoint).where(
            AssignmentCheckpoint.assignment_id == assignment.id,
            AssignmentCheckpoint.ordinal == ordinal,
        )
    ).one_or_none()
    if rule is None:
        rule = AssignmentCheckpoint(assignment_id=assignment.id, ordinal=ordinal)
        session.add(rule)

    rule.deadline_at = deadline_at
    rule.gates_stage = gates_stage
    session.flush()
    staff_actions.record(
        session, actor, "set_checkpoint_rule", "assignment", assignment.id,
        detail={"ordinal": ordinal, "gates_stage": gates_stage,
                "deadline_at": deadline_at.isoformat() if deadline_at else None},
    )
    return rule


def rules_for(session: Session, assignment_id: int) -> dict[int, AssignmentCheckpoint]:
    rows = session.scalars(
        select(AssignmentCheckpoint).where(AssignmentCheckpoint.assignment_id == assignment_id)
    )
    return {row.ordinal: row for row in rows}


def _checkpoints_in_pack(session: Session, workspace: Workspace) -> list[dict]:
    pack_version = session.get(PackVersion, workspace.pack_version_id)
    return sorted(
        (pack_version.manifest or {}).get("checkpoints", []),
        key=lambda c: c.get("ordinal") or 0,
    )


def _ordinal_of(session: Session, workspace: Workspace, checkpoint_key: str) -> int | None:
    for checkpoint in _checkpoints_in_pack(session, workspace):
        if checkpoint["key"] == checkpoint_key:
            return checkpoint.get("ordinal")
    return None


def checkpoint_deadline(
    session: Session, workspace: Workspace, checkpoint_key: str
) -> datetime | None:
    """When this student's attempts at this checkpoint close, accommodation included.

    Extended time is extended time; it would be a strange accommodation that stopped at the
    checkpoint standing in front of the work (I1.11).
    """
    ordinal = _ordinal_of(session, workspace, checkpoint_key)
    if ordinal is None:
        return None
    rule = rules_for(session, workspace.assignment_id).get(ordinal)
    if rule is None or rule.deadline_at is None:
        return None

    override = current_override(session, workspace.assignment_id, workspace.student_id)
    extra = getattr(override, "checkpoint_extension_hours", None) if override else None
    return rule.deadline_at + timedelta(hours=extra) if extra else rule.deadline_at


def checkpoint_is_closed(session: Session, workspace: Workspace, checkpoint_key: str) -> bool:
    deadline = checkpoint_deadline(session, workspace, checkpoint_key)
    return deadline is not None and datetime.now(UTC) >= deadline


def gate_refusal(session: Session, workspace: Workspace, stage: str) -> str | None:
    """The reason this stage is shut, or None if it is open.

    A gate is only ever a checkpoint the student has not passed yet — never a judgement about the
    figures they have recorded.
    """
    rules = rules_for(session, workspace.assignment_id)
    gates = [rule for rule in rules.values() if rule.gates_stage == stage]
    if not gates:
        return None

    by_ordinal = {c.get("ordinal"): c for c in _checkpoints_in_pack(session, workspace)}
    for rule in sorted(gates, key=lambda r: r.ordinal):
        checkpoint = by_ordinal.get(rule.ordinal)
        if checkpoint is None:
            continue  # this company has no such checkpoint; nothing to stand in the way
        if not checkpoint_state(session, workspace, checkpoint["key"]).passed:
            return messages.checkpoint_gate(rule.ordinal, STAGE_LABELS.get(stage, stage))
    return None
