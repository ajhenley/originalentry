"""The pure ledger engine (T6.2–T6.4).

Given a :class:`~originalentry.ledger.models.Snapshot`, derive ledger lines, account balances,
trial balances at each stage, and the subsidiary proof. Nothing here touches a database or
Flask; nothing is stored (D6 rule 3). Balances are debit-positive.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import (
    ADJUSTING,
    CLOSING,
    GENERAL,
    INDIVIDUAL,
    REGULAR,
    TOTAL,
    LedgerLine,
    Snapshot,
)

# Which entry kinds contribute at each trial-balance stage (T6.3).
STAGE_KINDS: dict[str, frozenset[str]] = {
    "unadjusted": frozenset({REGULAR}),
    "adjusted": frozenset({REGULAR, ADJUSTING}),
    "post_closing": frozenset({REGULAR, ADJUSTING, CLOSING}),
}


# ── Ledger-line derivation ──────────────────────────────────────────────────────────────

def general_ledger(snapshot: Snapshot) -> list[LedgerLine]:
    """Derive every general-ledger line from the active general postings (T6.2)."""
    out: list[LedgerLine] = []
    for posting in snapshot.general_postings:
        journal = snapshot.journals.get(posting.journal_key)
        if journal is None:
            continue
        entries = [
            snapshot.entries[eid]
            for eid in posting.entry_ids
            if eid in snapshot.entries and not snapshot.entries[eid].voided
        ]
        if not entries:
            continue
        reference = f"{journal.ref_prefix}{posting.ordinal}"

        if journal.kind == GENERAL:
            for entry in entries:
                for line in entry.lines:
                    out.append(
                        LedgerLine(
                            account_number=line.account_number,
                            date=entry.entry_date,
                            reference=reference,
                            journal_key=journal.key,
                            kind=entry.kind,
                            debit_cents=line.debit_cents,
                            credit_cents=line.credit_cents,
                            party_code=line.party_code,
                            source_entry_id=entry.id,
                        )
                    )
            continue

        # Special journal: columns are a view; posting mode decides the derived lines.
        run_date = max(e.entry_date for e in entries)
        for column in journal.columns:
            col_lines = [
                (e, line)
                for e in entries
                for line in e.lines
                if line.column_key == column.key
            ]
            if not col_lines:
                continue
            if column.posts == TOTAL:
                debit = sum(line.debit_cents for _, line in col_lines)
                credit = sum(line.credit_cents for _, line in col_lines)
                account_number = column.account_number or col_lines[0][1].account_number
                out.append(
                    LedgerLine(
                        account_number=account_number,
                        date=run_date,
                        reference=reference,
                        journal_key=journal.key,
                        kind=col_lines[0][0].kind,
                        debit_cents=debit,
                        credit_cents=credit,
                        party_code=None,
                        source_entry_id=None,
                    )
                )
            elif column.posts == INDIVIDUAL:
                for entry, line in col_lines:
                    out.append(
                        LedgerLine(
                            account_number=line.account_number,
                            date=entry.entry_date,
                            reference=reference,
                            journal_key=journal.key,
                            kind=entry.kind,
                            debit_cents=line.debit_cents,
                            credit_cents=line.credit_cents,
                            party_code=line.party_code,
                            source_entry_id=entry.id,
                        )
                    )
    return out


def subsidiary_ledger(snapshot: Snapshot) -> list[LedgerLine]:
    """Derive subsidiary-ledger lines: one per party line from active subsidiary postings."""
    out: list[LedgerLine] = []
    for posting in snapshot.subsidiary_postings:
        journal = snapshot.journals.get(posting.journal_key)
        if journal is None:
            continue
        reference = f"{journal.ref_prefix}{posting.ordinal}"
        for eid in posting.entry_ids:
            entry = snapshot.entries.get(eid)
            if entry is None or entry.voided:
                continue
            for line in entry.lines:
                if line.party_code is None:
                    continue
                out.append(
                    LedgerLine(
                        account_number=line.account_number,
                        date=entry.entry_date,
                        reference=reference,
                        journal_key=journal.key,
                        kind=entry.kind,
                        debit_cents=line.debit_cents,
                        credit_cents=line.credit_cents,
                        party_code=line.party_code,
                        source_entry_id=entry.id,
                    )
                )
    return out


# ── Balances ────────────────────────────────────────────────────────────────────────────

def account_balances(
    snapshot: Snapshot,
    ledger_lines: list[LedgerLine],
    kinds: frozenset[str],
) -> dict[str, int]:
    """Debit-positive balances: opening + posted debits − posted credits, for the given kinds."""
    bal: dict[str, int] = dict(snapshot.opening_account_cents)
    for line in ledger_lines:
        if line.kind in kinds:
            bal[line.account_number] = (
                bal.get(line.account_number, 0) + line.debit_cents - line.credit_cents
            )
    return bal


def balances(snapshot: Snapshot, stage: str = "adjusted") -> dict[str, int]:
    """Account balances at a trial-balance stage. ``stage`` is a key of :data:`STAGE_KINDS`."""
    return account_balances(snapshot, general_ledger(snapshot), STAGE_KINDS[stage])


# ── Trial balance ───────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TrialBalanceRow:
    account_number: str
    account_name: str
    debit_cents: int
    credit_cents: int
    sort_order: int = 0


@dataclass(frozen=True)
class TrialBalance:
    stage: str
    rows: tuple[TrialBalanceRow, ...]
    total_debit_cents: int
    total_credit_cents: int
    in_balance: bool
    difference_cents: int


def trial_balance(snapshot: Snapshot, stage: str = "unadjusted") -> TrialBalance:
    """Build a trial balance. Only accounts with a non-zero balance appear (T6.3)."""
    bals = balances(snapshot, stage)
    rows: list[TrialBalanceRow] = []
    for number, bal in bals.items():
        if bal == 0:
            continue
        acct = snapshot.accounts.get(number)
        name = acct.name if acct else number
        sort = acct.sort_order if acct else 0
        if bal > 0:
            rows.append(TrialBalanceRow(number, name, bal, 0, sort))
        else:
            rows.append(TrialBalanceRow(number, name, 0, -bal, sort))
    rows.sort(key=lambda r: (r.sort_order, r.account_number))
    total_debit = sum(r.debit_cents for r in rows)
    total_credit = sum(r.credit_cents for r in rows)
    difference = abs(total_debit - total_credit)
    return TrialBalance(
        stage=stage,
        rows=tuple(rows),
        total_debit_cents=total_debit,
        total_credit_cents=total_credit,
        in_balance=difference == 0,
        difference_cents=difference,
    )


# ── Subsidiary proof ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SubsidiaryPartyRow:
    party_code: str
    party_name: str
    balance_cents: int  # debit-positive


@dataclass(frozen=True)
class SubsidiaryProof:
    subsidiary_kind: str
    control_account_number: str | None
    control_balance_cents: int
    party_rows: tuple[SubsidiaryPartyRow, ...]
    party_total_cents: int
    agrees: bool
    difference_cents: int


def subsidiary_proof(snapshot: Snapshot, subsidiary_kind: str) -> SubsidiaryProof:
    """Prove the subsidiary total against its control account for one kind (T6.3)."""
    control = next(
        (a for a in snapshot.accounts.values() if a.subsidiary_kind == subsidiary_kind),
        None,
    )
    gl = general_ledger(snapshot)
    control_balance = 0
    control_number = control.number if control else None
    if control_number is not None:
        control_balance = snapshot.opening_account_cents.get(control_number, 0)
        for line in gl:
            if line.account_number == control_number:
                control_balance += line.debit_cents - line.credit_cents

    # Party balances: opening + subsidiary-ledger activity, for parties of this kind.
    party_bal: dict[str, int] = {
        code: snapshot.opening_party_cents.get(code, 0)
        for code, party in snapshot.parties.items()
        if party.kind == subsidiary_kind
    }
    for line in subsidiary_ledger(snapshot):
        code = line.party_code
        if code is None:
            continue
        # A party line counts toward this ledger only when it sits on this kind's own control
        # account. The forms accept a party on any account (they only *require* one on a subsidiary
        # account), so a customer mistakenly tagged on a cash or expense line must not inflate the
        # receivables total against a control it never touched -- that would fail the proof, and
        # cost subsidiary_agreement marks, for a slip unrelated to the control relationship.
        if control_number is None or line.account_number != control_number:
            continue
        party = snapshot.parties.get(code)
        if party is None or party.kind != subsidiary_kind:
            continue
        party_bal[code] = party_bal.get(code, 0) + line.debit_cents - line.credit_cents

    rows = tuple(
        SubsidiaryPartyRow(code, snapshot.parties[code].name, bal)
        for code, bal in party_bal.items()
        if code in snapshot.parties
    )
    party_total = sum(r.balance_cents for r in rows)
    difference = abs(party_total - control_balance)
    return SubsidiaryProof(
        subsidiary_kind=subsidiary_kind,
        control_account_number=control_number,
        control_balance_cents=control_balance,
        party_rows=rows,
        party_total_cents=party_total,
        agrees=difference == 0,
        difference_cents=difference,
    )
