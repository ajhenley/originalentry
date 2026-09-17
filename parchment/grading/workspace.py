"""Turning a workspace into gradeable work (T8.1).

This is the only place that reads the database for grading, and the only place outside
``checkpoints`` that reads an answer key. Everything past here is pure: the engine is handed
dataclasses and hands back points, so a marking rule can be argued about without a database.

Loading is bounded: the ledger snapshot, one query for the triage, one for the statement rows,
and one for the key.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ledger.snapshot import load_snapshot
from ..models import (
    Account,
    AnswerKey,
    Disposition,
    PackVersion,
    SourceDocument,
    StatementDraft,
    StatementLine,
    Workspace,
)
from ..packs import schema
from .engine import grade
from .models import GradeResult, StatementRow, StudentWork


def load_work(session: Session, workspace: Workspace) -> StudentWork:
    choices, reasons = _dispositions(session, workspace)
    return StudentWork(
        snapshot=load_snapshot(session, workspace),
        dispositions=choices,
        disposition_reasons=reasons,
        statements=_statements(session, workspace),
    )


def grade_workspace(session: Session, workspace: Workspace) -> GradeResult:
    """Grade one workspace against its pinned pack version and its own variant's key."""
    pack_version = session.get(PackVersion, workspace.pack_version_id)
    pack = schema.load_pack(pack_version.manifest)
    key_row = session.execute(
        select(AnswerKey).where(
            AnswerKey.pack_version_id == workspace.pack_version_id,
            AnswerKey.variant_id == workspace.variant_id,
        )
    ).scalar_one_or_none()
    key = schema.load_answer_key(key_row.payload if key_row else {"variant": ""})
    return grade(load_work(session, workspace), pack, key)


def _dispositions(
    session: Session, workspace: Workspace
) -> tuple[dict[str, str], dict[str, str]]:
    rows = session.execute(
        select(SourceDocument.ref, Disposition.choice, Disposition.reason)
        .join(Disposition, Disposition.document_id == SourceDocument.id)
        .where(
            Disposition.workspace_id == workspace.id,
            Disposition.superseded_at.is_(None),
        )
    ).all()
    choices = {ref: choice for ref, choice, _ in rows}
    reasons = {ref: reason for ref, _, reason in rows if reason}
    return choices, reasons


def _statements(session: Session, workspace: Workspace) -> dict[str, tuple[StatementRow, ...]]:
    rows = session.execute(
        select(StatementDraft.statement_type, StatementLine, Account.number)
        .join(StatementLine, StatementLine.draft_id == StatementDraft.id)
        .outerjoin(Account, Account.id == StatementLine.account_id)
        .where(StatementDraft.workspace_id == workspace.id)
        .order_by(StatementDraft.statement_type, StatementLine.position)
    ).all()

    statements: dict[str, list[StatementRow]] = {}
    for statement_type, line, account_number in rows:
        statements.setdefault(statement_type, []).append(
            StatementRow(
                kind=line.kind,
                label=line.label,
                account_number=account_number,
                subtotal_type=line.subtotal_type,
                amount_cents=line.amount_cents,
                indent=line.indent,
            )
        )
    return {key: tuple(value) for key, value in statements.items()}
