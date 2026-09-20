"""Journal-entry writes. Called inside :func:`workspace_write`, so these operate on the locked
workspace and never commit themselves.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import messages
from ..forms.entries import EntryCommand
from ..models import (
    KIND_ADJUSTING,
    KIND_CLOSING,
    Account,
    EntryLine,
    JournalEntry,
    Party,
    SourceDocument,
    Workspace,
)
from .errors import WriteRefused
from .posting import active_posted_entry_ids


def record_entry(session: Session, workspace: Workspace, command: EntryCommand) -> JournalEntry:
    """Create a journal entry and its lines. Idempotent on ``client_key`` (T7.4): a repeated key
    returns the entry that already exists rather than creating a duplicate."""
    existing = session.execute(
        select(JournalEntry).where(
            JournalEntry.workspace_id == workspace.id,
            JournalEntry.client_key == command.client_key,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    # A checkpoint the instructor put in front of this stage has to be passed first (S6.3).
    # Local import: checkpoint_rules reads the entry kinds this module owns.
    from .checkpoint_rules import ADJUSTING, CLOSING, gate_refusal

    stage = {KIND_ADJUSTING: ADJUSTING, KIND_CLOSING: CLOSING}.get(command.kind)
    if stage is not None:
        shut = gate_refusal(session, workspace, stage)
        if shut is not None:
            raise WriteRefused(shut)

    pv_id = workspace.pack_version_id
    account_id = {
        a.number: a.id
        for a in session.scalars(select(Account).where(Account.pack_version_id == pv_id))
    }
    party_id = {
        p.code: p.id
        for p in session.scalars(select(Party).where(Party.pack_version_id == pv_id))
    }
    document_id = None
    if command.document_ref is not None:
        document_id = session.execute(
            select(SourceDocument.id).where(
                SourceDocument.pack_version_id == pv_id,
                SourceDocument.ref == command.document_ref,
            )
        ).scalar_one_or_none()

    next_seq = (
        session.execute(
            select(func.coalesce(func.max(JournalEntry.seq), 0) + 1).where(
                JournalEntry.workspace_id == workspace.id,
                JournalEntry.journal_key == command.journal_key,
            )
        ).scalar_one()
    )

    entry = JournalEntry(
        workspace_id=workspace.id,
        pack_version_id=pv_id,
        journal_key=command.journal_key,
        seq=next_seq,
        entry_date=command.entry_date,
        document_id=document_id,
        description=command.description,
        kind=command.kind,
        client_key=command.client_key,
    )
    session.add(entry)
    session.flush()

    for i, line in enumerate(command.lines, start=1):
        session.add(
            EntryLine(
                entry_id=entry.id,
                workspace_id=workspace.id,
                pack_version_id=pv_id,
                line_no=i,
                column_key=line.column_key,
                account_id=account_id[line.account_number],
                party_id=party_id.get(line.party_code) if line.party_code else None,
                debit_cents=line.debit_cents,
                credit_cents=line.credit_cents,
                memo=line.memo,
            )
        )
    session.flush()
    return entry


def void_entry(
    session: Session, workspace: Workspace, entry_public_id: str, reason: str
) -> JournalEntry:
    entry = session.execute(
        select(JournalEntry).where(
            JournalEntry.workspace_id == workspace.id,
            JournalEntry.public_id == entry_public_id,
        )
    ).scalar_one_or_none()
    if entry is None:
        raise WriteRefused(messages.ENTRY_IS_POSTED)
    if entry.voided_at is not None:
        return entry
    posted = active_posted_entry_ids(session, workspace, "general") | active_posted_entry_ids(
        session, workspace, "subsidiary"
    )
    if entry.id in posted:
        raise WriteRefused(messages.ENTRY_IS_POSTED)
    entry.voided_at = datetime.now(UTC)
    entry.void_reason = reason
    return entry
