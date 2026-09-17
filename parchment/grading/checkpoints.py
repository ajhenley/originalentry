"""Checkpoint evaluation (T8.3).

``evaluate`` reads one answer value from the key for the workspace's variant, compares it to the
cent, and returns a boolean. The answer value never leaves this function — it does not reach a
template or a response (A8). This module reads the answer_key table, which only ``grading/`` and
``staff/`` may do (D6 rule 6).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AnswerKey, Workspace


def _answer_value(session: Session, workspace: Workspace, checkpoint_key: str) -> int | None:
    key = session.execute(
        select(AnswerKey).where(
            AnswerKey.pack_version_id == workspace.pack_version_id,
            AnswerKey.variant_id == workspace.variant_id,
        )
    ).scalar_one_or_none()
    if key is None:
        return None
    value = (key.payload or {}).get("checkpoints", {}).get(checkpoint_key)
    return int(value) if value is not None else None


def evaluate(
    session: Session, workspace: Workspace, checkpoint_key: str, submitted_cents: int
) -> bool:
    """True iff the student's submitted figure equals the key's checkpoint answer to the cent."""
    answer = _answer_value(session, workspace, checkpoint_key)
    if answer is None:
        return False
    return answer == submitted_cents
