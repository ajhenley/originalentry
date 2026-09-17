"""Submission. Marks a workspace submitted and stamps how late it was; the app computes no
penalty (tension 10). After this the write path refuses further writes (read-only)."""

from __future__ import annotations

import math
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from .. import messages
from ..models import Assignment, Workspace
from .errors import WriteRefused
from .write import _effective_close


def submit_workspace(session: Session, workspace: Workspace) -> Workspace:
    if workspace.status == "submitted":
        raise WriteRefused(messages.READ_ONLY_SUBMITTED)

    now = datetime.now(UTC)
    assignment = session.get(Assignment, workspace.assignment_id)
    due = _effective_close(assignment) if assignment else None
    late_hours = 0
    if due is not None and now > due:
        late_hours = math.ceil((now - due).total_seconds() / 3600)

    workspace.status = "submitted"
    workspace.submitted_at = now
    workspace.submitted_late_hours = late_hours
    return workspace
