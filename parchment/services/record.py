"""Assemble a workspace's whole record for the print page (T10.5, A-print).

The print record is the derived truth in one place: dispositions, journals (voids included),
postings and reversals, the ledgers, the three trial balances, the statements, the checkpoint
attempts and the activity timeline. The browser saves it as PDF; there is no PDF library
(WeasyPrint is not used, T16).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ledger import balances, subsidiary_proof, trial_balance
from ..ledger.engine import TrialBalanceRow
from ..ledger.snapshot import load_snapshot
from ..models import (
    Account,
    ActivityEvent,
    CheckpointAttempt,
    Disposition,
    JournalEntry,
    Party,
    PostingRun,
    SourceDocument,
)

_STAGES = ("unadjusted", "adjusted", "post_closing")


@dataclass
class RecordEntry:
    seq: int
    date: object
    kind: str
    voided: bool
    lines: list[dict] = field(default_factory=list)


@dataclass
class WorkspaceRecord:
    trial_balances: dict = field(default_factory=dict)
    general_ledger: list = field(default_factory=list)
    subsidiary: list = field(default_factory=list)
    journals: list = field(default_factory=list)
    postings: list = field(default_factory=list)
    dispositions: list = field(default_factory=list)
    checkpoints: list = field(default_factory=list)
    timeline: list = field(default_factory=list)


def workspace_record(
    session: Session, workspace, manifest: dict, subsidiary_kinds
) -> WorkspaceRecord:
    snapshot = load_snapshot(session, workspace)
    pv_id = workspace.pack_version_id

    account_name = {
        a.id: f"{a.number} {a.name}"
        for a in session.scalars(select(Account).where(Account.pack_version_id == pv_id))
    }
    party_name = {
        p.id: p.name
        for p in session.scalars(select(Party).where(Party.pack_version_id == pv_id))
    }
    doc_ref = {
        d.id: d.display_ref
        for d in session.scalars(
            select(SourceDocument).where(SourceDocument.pack_version_id == pv_id)
        )
    }

    record = WorkspaceRecord()
    record.trial_balances = {stage: trial_balance(snapshot, stage) for stage in _STAGES}

    bals = balances(snapshot, "adjusted")
    gl = []
    for number, bal in bals.items():
        if bal == 0:
            continue
        acct = snapshot.accounts.get(number)
        gl.append(TrialBalanceRow(number, acct.name if acct else number,
                                  bal if bal > 0 else 0, -bal if bal < 0 else 0,
                                  acct.sort_order if acct else 0))
    record.general_ledger = sorted(gl, key=lambda r: (r.sort_order, r.account_number))

    record.subsidiary = [subsidiary_proof(snapshot, kind) for kind in subsidiary_kinds]

    # Journals with every entry, voids included.
    entries = list(
        session.scalars(
            select(JournalEntry).where(JournalEntry.workspace_id == workspace.id)
            .order_by(JournalEntry.journal_key, JournalEntry.seq)
        )
    )
    journal_names = {j["key"]: j["name"] for j in manifest.get("journals", [])}
    by_journal: dict[str, list[RecordEntry]] = {}
    for e in entries:
        lines = [
            {"account": account_name.get(line.account_id, ""),
             "party": party_name.get(line.party_id) if line.party_id else None,
             "debit_cents": line.debit_cents, "credit_cents": line.credit_cents}
            for line in sorted(e.lines, key=lambda x: x.line_no)
        ]
        by_journal.setdefault(e.journal_key, []).append(
            RecordEntry(seq=e.seq, date=e.entry_date, kind=e.kind,
                        voided=e.voided_at is not None, lines=lines)
        )
    record.journals = [
        {"name": journal_names.get(key, key), "entries": rows}
        for key, rows in by_journal.items()
    ]

    record.postings = [
        {"journal_key": r.journal_key, "target": r.target, "ordinal": r.ordinal,
         "reversed": r.reversed_at is not None, "reason": r.reversal_reason}
        for r in session.scalars(
            select(PostingRun).where(PostingRun.workspace_id == workspace.id)
            .order_by(PostingRun.target, PostingRun.ordinal)
        )
    ]

    record.dispositions = [
        {"document": doc_ref.get(d.document_id, str(d.document_id)),
         "choice": d.choice, "reason": d.reason}
        for d in session.scalars(
            select(Disposition).where(
                Disposition.workspace_id == workspace.id, Disposition.superseded_at.is_(None)
            )
        )
    ]

    record.checkpoints = [
        {"key": a.checkpoint_key, "attempt_no": a.attempt_no, "passed": a.passed}
        for a in session.scalars(
            select(CheckpointAttempt).where(CheckpointAttempt.workspace_id == workspace.id)
            .order_by(CheckpointAttempt.checkpoint_key, CheckpointAttempt.attempt_no)
        )
    ]

    record.timeline = [
        {"kind": ev.kind, "at": ev.at}
        for ev in session.scalars(
            select(ActivityEvent).where(ActivityEvent.workspace_id == workspace.id)
            .order_by(ActivityEvent.at)
        )
    ]
    return record
