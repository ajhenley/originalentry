"""The one place that turns database rows into the engine's dataclasses (T6, T2).

This is the *only* module in ``ledger/`` allowed to import ``models`` and SQLAlchemy — the guard
test exempts it. Everything else in the engine stays pure. The loader is bounded (a handful of
queries, no lazy loading) so the engine's timing guarantees hold.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Account as AccountRow,
)
from ..models import (
    AccountOpeningBalance,
    EntryLine,
    JournalEntry,
    PartyOpeningBalance,
    PostingRun,
    PostingRunEntry,
    SourceDocument,
    Workspace,
)
from ..models import (
    Party as PartyRow,
)
from .models import (
    Account,
    Entry,
    Journal,
    JournalColumn,
    Line,
    Party,
    Posting,
    Snapshot,
)


def _journals_from_manifest(manifest: dict) -> dict[str, Journal]:
    journals: dict[str, Journal] = {}
    for j in manifest.get("journals", []):
        columns = tuple(
            JournalColumn(
                key=c["key"],
                label=c.get("label", c["key"]),
                side=c["side"],
                account_number=c.get("account"),
                posts=c.get("posts", "individual"),
                subsidiary_kind=c.get("subsidiary_kind"),
            )
            for c in j.get("columns", [])
        )
        journals[j["key"]] = Journal(
            key=j["key"],
            name=j.get("name", j["key"]),
            ref_prefix=j.get("ref_prefix", ""),
            kind=j.get("kind", "general"),
            columns=columns,
        )
    return journals


def load_snapshot(session: Session, workspace: Workspace) -> Snapshot:
    """Load one workspace into an engine :class:`Snapshot`, scoped to its pinned pack version
    and variant."""
    pv_id = workspace.pack_version_id
    variant_id = workspace.variant_id

    account_rows = session.scalars(
        select(AccountRow).where(AccountRow.pack_version_id == pv_id)
    ).all()
    party_rows = session.scalars(
        select(PartyRow).where(PartyRow.pack_version_id == pv_id)
    ).all()

    id_to_account_number = {a.id: a.number for a in account_rows}
    id_to_party_code = {p.id: p.code for p in party_rows}

    accounts = {
        a.number: Account(
            number=a.number,
            name=a.name,
            account_type=a.account_type,
            normal_balance=a.normal_balance,
            statement_section=a.statement_section,
            roles=tuple(a.roles or ()),
            subsidiary_kind=a.subsidiary_kind,
            sort_order=a.sort_order,
        )
        for a in account_rows
    }
    parties = {
        p.code: Party(code=p.code, kind=p.kind, name=p.name) for p in party_rows
    }

    # Opening balances for this variant only (debit-positive).
    opening_account = {
        id_to_account_number[account_id]: cents
        for account_id, cents in session.execute(
            select(AccountOpeningBalance.account_id, AccountOpeningBalance.balance_cents).where(
                AccountOpeningBalance.variant_id == variant_id
            )
        )
        if account_id in id_to_account_number
    }
    opening_party = {
        id_to_party_code[party_id]: cents
        for party_id, cents in session.execute(
            select(PartyOpeningBalance.party_id, PartyOpeningBalance.balance_cents).where(
                PartyOpeningBalance.variant_id == variant_id
            )
        )
        if party_id in id_to_party_code
    }

    # Entries and their lines. An entry carries the reference of the document it records, which
    # is what every document-by-document grading component matches on (T8.2).
    document_refs = dict(
        session.execute(
            select(SourceDocument.id, SourceDocument.ref).where(
                SourceDocument.pack_version_id == pv_id
            )
        ).all()
    )
    entry_rows = session.scalars(
        select(JournalEntry).where(JournalEntry.workspace_id == workspace.id)
    ).all()
    entries: dict[int, Entry] = {}
    lines_by_entry: dict[int, list[Line]] = {e.id: [] for e in entry_rows}
    if entry_rows:
        line_rows = session.scalars(
            select(EntryLine).where(EntryLine.entry_id.in_(list(lines_by_entry)))
        ).all()
        for line in line_rows:
            lines_by_entry[line.entry_id].append(
                Line(
                    line_no=line.line_no,
                    account_number=id_to_account_number.get(line.account_id, ""),
                    debit_cents=line.debit_cents,
                    credit_cents=line.credit_cents,
                    column_key=line.column_key,
                    party_code=id_to_party_code.get(line.party_id) if line.party_id else None,
                    memo=line.memo,
                )
            )
    for e in entry_rows:
        entries[e.id] = Entry(
            id=e.id,
            journal_key=e.journal_key,
            entry_date=e.entry_date,
            kind=e.kind,
            lines=tuple(sorted(lines_by_entry[e.id], key=lambda line: line.line_no)),
            document_ref=document_refs.get(e.document_id),
            description=e.description,
            voided=e.voided_at is not None,
            seq=e.seq,
        )

    # Active postings (a run is active unless reversed; entries are active per posting_run_entry).
    general_postings, subsidiary_postings = _load_postings(session, workspace.id)
    pack_manifest = _load_manifest(session, pv_id)

    return Snapshot(
        accounts=accounts,
        parties=parties,
        journals=_journals_from_manifest(pack_manifest),
        opening_account_cents=opening_account,
        opening_party_cents=opening_party,
        entries=entries,
        general_postings=general_postings,
        subsidiary_postings=subsidiary_postings,
    )


def _load_manifest(session: Session, pack_version_id: int) -> dict:
    from ..models import PackVersion

    pv = session.get(PackVersion, pack_version_id)
    return pv.manifest if pv and pv.manifest else {}


def _load_postings(
    session: Session, workspace_id: int
) -> tuple[tuple[Posting, ...], tuple[Posting, ...]]:
    runs = session.scalars(
        select(PostingRun).where(
            PostingRun.workspace_id == workspace_id, PostingRun.reversed_at.is_(None)
        )
    ).all()
    if not runs:
        return (), ()
    run_by_id = {r.id: r for r in runs}
    active_entries: dict[int, list[int]] = {r.id: [] for r in runs}
    for pre in session.scalars(
        select(PostingRunEntry).where(
            PostingRunEntry.posting_run_id.in_(list(run_by_id)),
            PostingRunEntry.active.is_(True),
        )
    ).all():
        if pre.posting_run_id in active_entries:
            active_entries[pre.posting_run_id].append(pre.entry_id)

    general: list[Posting] = []
    subsidiary: list[Posting] = []
    for run in runs:
        posting = Posting(
            journal_key=run.journal_key,
            target=run.target,
            ordinal=run.ordinal,
            entry_ids=tuple(active_entries[run.id]),
        )
        (general if run.target == "general" else subsidiary).append(posting)
    return tuple(general), tuple(subsidiary)
