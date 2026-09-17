"""The Progress screen's data (I2.1–I2.3, I2.5).

One row per student per assignment, built from six bulk queries rather than a query per student,
so a section of forty is one page load. Nothing here is stored: a row is derived from the work
itself every time it is read (D6 rule 3).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    ActivityEvent,
    Assignment,
    CheckpointAttempt,
    Disposition,
    JournalEntry,
    PostingRun,
    PostingRunEntry,
    SourceDocument,
    StatementLine,
    User,
    Workspace,
)
from ..models.work import KIND_ADJUSTING, KIND_CLOSING, KIND_REGULAR, TARGET_GENERAL
from .activity import REFUSED_SAVE
from .checkpoints import DEFAULT_MAX_ATTEMPTS
from .grades import submission_status

# The stages a workspace passes through, in order (T6.5).
NOT_STARTED = "Not started"
DOCUMENTS = "Documents"
JOURNALISING = "Journalising"
POSTED = "Posted"
ADJUSTING = "Adjusting"
STATEMENTS = "Statements"
CLOSED = "Closed"
SUBMITTED = "Submitted"

NOT_STARTED_WINDOW = timedelta(hours=48)


@dataclass(frozen=True)
class Lockout:
    checkpoint_key: str
    figures: tuple[int, ...]  # every figure the student submitted, in order


@dataclass(frozen=True)
class RefusedSave:
    document_ref: str | None
    reason: str
    at: datetime | None


@dataclass(frozen=True)
class ProgressRow:
    workspace_public_id: str
    student_name: str
    student_email: str
    variant_id: int
    documents_triaged: int
    documents_total: int
    journals_posted: int
    stage: str
    last_activity_at: datetime | None
    submission_status: str
    locked_checkpoints: tuple[Lockout, ...] = ()
    last_refused: RefusedSave | None = None
    not_started_flag: bool = False


def assignment_progress(session: Session, assignment: Assignment) -> list[ProgressRow]:
    workspaces = list(
        session.execute(
            select(Workspace, User)
            .join(User, Workspace.student_id == User.id)
            .where(Workspace.assignment_id == assignment.id, Workspace.archived_at.is_(None))
            .order_by(User.email)
        ).all()
    )
    if not workspaces:
        return []

    ids = [ws.id for ws, _ in workspaces]
    documents_total = session.execute(
        select(func.count()).select_from(SourceDocument).where(
            SourceDocument.pack_version_id == assignment.fixed_pack_version_id
        )
    ).scalar_one() if assignment.fixed_pack_version_id else 0

    triaged = _triaged_counts(session, ids)
    entries = _entries(session, ids)
    posted_ids = _posted_entry_ids(session, ids)
    statements = _statement_counts(session, ids)
    lockouts = _lockouts(session, ids)
    refusals = _last_refusals(session, ids)

    rows = []
    for ws, student in workspaces:
        own_entries = entries.get(ws.id, [])
        posted = posted_ids.get(ws.id, set())
        journals_posted = _journals_posted(own_entries, posted)
        status = submission_status(session, ws)
        rows.append(
            ProgressRow(
                workspace_public_id=ws.public_id,
                student_name=f"{student.given_name} {student.family_name}".strip()
                or student.email,
                student_email=student.email,
                variant_id=ws.variant_id,
                documents_triaged=triaged.get(ws.id, 0),
                documents_total=documents_total,
                journals_posted=journals_posted,
                stage=_stage(
                    triaged.get(ws.id, 0), own_entries, posted, statements.get(ws.id, 0),
                    ws.status == "submitted",
                ),
                last_activity_at=ws.last_activity_at,
                submission_status=status,
                locked_checkpoints=lockouts.get(ws.id, ()),
                last_refused=refusals.get(ws.id),
                not_started_flag=_not_started_flag(ws, assignment),
            )
        )
    return rows


def _triaged_counts(session: Session, ids: list[int]) -> dict[int, int]:
    return dict(
        session.execute(
            select(Disposition.workspace_id, func.count())
            .where(Disposition.workspace_id.in_(ids), Disposition.superseded_at.is_(None))
            .group_by(Disposition.workspace_id)
        ).all()
    )


def _entries(session: Session, ids: list[int]) -> dict[int, list[tuple[int, str, str]]]:
    """(entry id, journal key, kind) per workspace, voided entries left out."""
    out: dict[int, list[tuple[int, str, str]]] = {}
    for workspace_id, entry_id, journal_key, kind in session.execute(
        select(JournalEntry.workspace_id, JournalEntry.id, JournalEntry.journal_key,
               JournalEntry.kind)
        .where(JournalEntry.workspace_id.in_(ids), JournalEntry.voided_at.is_(None))
    ):
        out.setdefault(workspace_id, []).append((entry_id, journal_key, kind))
    return out


def _posted_entry_ids(session: Session, ids: list[int]) -> dict[int, set[int]]:
    out: dict[int, set[int]] = {}
    for workspace_id, entry_id in session.execute(
        select(PostingRun.workspace_id, PostingRunEntry.entry_id)
        .join(PostingRunEntry, PostingRunEntry.posting_run_id == PostingRun.id)
        .where(
            PostingRun.workspace_id.in_(ids),
            PostingRun.target == TARGET_GENERAL,
            PostingRun.reversed_at.is_(None),
            PostingRunEntry.active.is_(True),
        )
    ):
        out.setdefault(workspace_id, set()).add(entry_id)
    return out


def _statement_counts(session: Session, ids: list[int]) -> dict[int, int]:
    return dict(
        session.execute(
            select(StatementLine.workspace_id, func.count())
            .where(StatementLine.workspace_id.in_(ids))
            .group_by(StatementLine.workspace_id)
        ).all()
    )


def _lockouts(session: Session, ids: list[int]) -> dict[int, tuple[Lockout, ...]]:
    attempts: dict[tuple[int, str], list[tuple[int, bool]]] = {}
    for workspace_id, key, _attempt_no, value, passed in session.execute(
        select(CheckpointAttempt.workspace_id, CheckpointAttempt.checkpoint_key,
               CheckpointAttempt.attempt_no, CheckpointAttempt.value_cents,
               CheckpointAttempt.passed)
        .where(CheckpointAttempt.workspace_id.in_(ids))
        .order_by(CheckpointAttempt.attempt_no)
    ):
        attempts.setdefault((workspace_id, key), []).append((value, passed))

    out: dict[int, list[Lockout]] = {}
    for (workspace_id, key), rows in attempts.items():
        if any(passed for _, passed in rows) or len(rows) < DEFAULT_MAX_ATTEMPTS:
            continue
        out.setdefault(workspace_id, []).append(
            Lockout(checkpoint_key=key, figures=tuple(value for value, _ in rows))
        )
    return {workspace_id: tuple(rows) for workspace_id, rows in out.items()}


def _last_refusals(session: Session, ids: list[int]) -> dict[int, RefusedSave]:
    out: dict[int, RefusedSave] = {}
    for workspace_id, detail, at in session.execute(
        select(ActivityEvent.workspace_id, ActivityEvent.detail, ActivityEvent.at)
        .where(ActivityEvent.workspace_id.in_(ids), ActivityEvent.kind == REFUSED_SAVE)
        .order_by(ActivityEvent.at)
    ):
        out[workspace_id] = RefusedSave(
            document_ref=(detail or {}).get("document"),
            reason=(detail or {}).get("reason", ""),
            at=at,
        )
    return out


def _journals_posted(entries, posted: set[int]) -> int:
    """A journal counts as posted when it holds entries and none of them is waiting."""
    journals: dict[str, list[int]] = {}
    for entry_id, journal_key, _ in entries:
        journals.setdefault(journal_key, []).append(entry_id)
    return sum(
        1 for entry_ids in journals.values() if entry_ids and all(i in posted for i in entry_ids)
    )


def _stage(triaged: int, entries, posted: set[int], statement_rows: int, submitted: bool) -> str:
    if submitted:
        return SUBMITTED
    kinds_posted = {kind for entry_id, _, kind in entries if entry_id in posted}
    if KIND_CLOSING in kinds_posted:
        return CLOSED
    if statement_rows:
        return STATEMENTS
    if KIND_ADJUSTING in kinds_posted:
        return ADJUSTING
    regular = [entry_id for entry_id, _, kind in entries if kind == KIND_REGULAR]
    if regular and all(entry_id in posted for entry_id in regular):
        return POSTED
    if entries:
        return JOURNALISING
    if triaged:
        return DOCUMENTS
    return NOT_STARTED


def _not_started_flag(workspace: Workspace, assignment: Assignment) -> bool:
    """Flag a student who has not begun within 48 hours of the due date (I2.2)."""
    if workspace.status != "not_started" or assignment.due_at is None:
        return False
    return datetime.now(assignment.due_at.tzinfo) >= assignment.due_at - NOT_STARTED_WINDOW
