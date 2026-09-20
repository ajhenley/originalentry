"""Statement draft writes (S5.5). Called inside :func:`workspace_write`.

A statement is the student's own layout, so saving replaces the draft's rows in place and bumps
its version. Drafts are the one thing the design overwrites rather than supersedes (tension 9);
the journals, postings and dispositions behind them are untouched.

Account numbers are resolved to this workspace's pack version here, the same way a disposition
resolves a document reference. An account from another company's chart is refused before the
composite foreign key would reject it.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import messages, money
from ..forms.statements import StatementCommand
from ..ledger import balances
from ..ledger.snapshot import load_snapshot
from ..models import Account, StatementDraft, StatementLine, Workspace
from .errors import WriteRefused


def load_draft(
    session: Session, workspace: Workspace, statement_type: str
) -> StatementDraft | None:
    return session.scalars(
        select(StatementDraft).where(
            StatementDraft.workspace_id == workspace.id,
            StatementDraft.statement_type == statement_type,
        )
    ).one_or_none()


def statement_counts(session: Session, workspace: Workspace) -> dict[str, int]:
    """statement_type -> number of rows, for the submission checklist (S6.4)."""
    rows = session.execute(
        select(StatementDraft.statement_type, func.count(StatementLine.id))
        .join(StatementLine, StatementLine.draft_id == StatementDraft.id)
        .where(StatementDraft.workspace_id == workspace.id)
        .group_by(StatementDraft.statement_type)
    ).all()
    return {statement_type: count for statement_type, count in rows}


def save_statement(
    session: Session, workspace: Workspace, command: StatementCommand
) -> StatementDraft:
    account_ids = _resolve_accounts(session, workspace, command)

    draft = load_draft(session, workspace, command.statement_type)
    if draft is None:
        draft = StatementDraft(
            workspace_id=workspace.id, statement_type=command.statement_type, version=0
        )
        session.add(draft)
        session.flush()

    draft.lines.clear()  # the student's layout is replaced wholesale, not merged
    session.flush()

    for position, row in enumerate(command.rows):
        draft.lines.append(
            StatementLine(
                workspace_id=workspace.id,
                pack_version_id=workspace.pack_version_id,
                position=position,
                kind=row.kind,
                label=row.label,
                subtotal_type=row.subtotal_type,
                account_id=account_ids.get(row.account_number),
                amount_cents=row.amount_cents,
                indent=row.indent,
                amount_column=row.amount_column,
            )
        )

    draft.header = dict(command.header)
    draft.version += 1
    draft.updated_at = datetime.now(UTC)
    session.flush()
    return draft


def _resolve_accounts(
    session: Session, workspace: Workspace, command: StatementCommand
) -> dict[str, int]:
    numbers = {row.account_number for row in command.rows if row.account_number}
    if not numbers:
        return {}
    found = dict(
        session.execute(
            select(Account.number, Account.id).where(
                Account.pack_version_id == workspace.pack_version_id,
                Account.number.in_(numbers),
            )
        ).all()
    )
    if set(found) != numbers:
        raise WriteRefused(messages.LINE_NEEDS_ACCOUNT)
    return found


def draft_rows(
    session: Session, workspace: Workspace, draft: StatementDraft | None
) -> list[dict]:
    """A saved draft as form values, so the builder shows the student's rows as they left them."""
    if draft is None:
        return []
    numbers = dict(
        session.execute(
            select(Account.id, Account.number).where(
                Account.pack_version_id == workspace.pack_version_id
            )
        ).all()
    )
    return [
        {
            "kind": line.kind,
            "label": line.label,
            "account_number": numbers.get(line.account_id),
            "subtotal_type": line.subtotal_type,
            "amount": money.format_cents(line.amount_cents)
            if line.amount_cents is not None
            else "",
            "indent": line.indent,
            "amount_column": line.amount_column,
        }
        for line in draft.lines
    ]


def own_figures(session: Session, workspace: Workspace, stage: str = "adjusted") -> list[dict]:
    """The student's *own* balances for the builder's side panel — never the key (A8).

    Accounts with a zero balance are left out, and the order follows the pack's chart.
    """
    snapshot = load_snapshot(session, workspace)
    rows = [
        {"number": number, "name": snapshot.accounts[number].name, "amount_cents": amount}
        for number, amount in balances(snapshot, stage).items()
        if amount != 0 and number in snapshot.accounts
    ]
    rows.sort(key=lambda row: snapshot.accounts[row["number"]].sort_order)
    return rows
