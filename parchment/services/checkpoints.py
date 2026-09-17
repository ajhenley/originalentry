"""Checkpoint attempt writes and state. The pass/fail decision is made by
``grading.checkpoints.evaluate`` (the only place that reads the answer); this module just records
the attempt and summarises how many remain. All attempts are kept (D4).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import CheckpointAttempt, Workspace

DEFAULT_MAX_ATTEMPTS = 3


@dataclass(frozen=True)
class CheckpointState:
    key: str
    attempts_used: int
    passed: bool
    remaining: int
    locked: bool  # out of attempts and not passed


def checkpoint_state(
    session: Session, workspace: Workspace, checkpoint_key: str,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> CheckpointState:
    attempts = list(
        session.scalars(
            select(CheckpointAttempt).where(
                CheckpointAttempt.workspace_id == workspace.id,
                CheckpointAttempt.checkpoint_key == checkpoint_key,
            )
        )
    )
    used = len(attempts)
    passed = any(a.passed for a in attempts)
    remaining = max(0, max_attempts - used)
    return CheckpointState(
        key=checkpoint_key,
        attempts_used=used,
        passed=passed,
        remaining=remaining,
        locked=(not passed and remaining == 0),
    )


def record_attempt(
    session: Session, workspace: Workspace, checkpoint_key: str,
    submitted_cents: int, passed: bool,
) -> CheckpointAttempt:
    state = checkpoint_state(session, workspace, checkpoint_key)
    attempt = CheckpointAttempt(
        workspace_id=workspace.id,
        checkpoint_key=checkpoint_key,
        attempt_no=state.attempts_used + 1,
        value_cents=submitted_cents,
        passed=passed,
    )
    session.add(attempt)
    session.flush()
    return attempt
