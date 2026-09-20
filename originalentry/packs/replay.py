"""Replay an answer key through the pure ledger engine, in memory (for V9 / A2-at-upload).

Given a pack and a variant's key, build an engine :class:`Snapshot` by journalising the key's
expected entries, its independent adjustments, and the closing entries the cycle implies, then
posting everything. Feeding that snapshot to the engine must reproduce ``expected_balances`` to
the cent — that is what V9 checks before a pack is ever used.

Closing is generated here (the key does not enumerate it): every temporary account is closed to
Income Summary, then Income Summary to the retained-earnings account. Dividends/drawings close
straight to retained earnings.

Limitation: only ``independent`` adjustments (whose amount is in the key) are replayed. A pack
whose ``expected_balances`` depend on a ``dependent`` adjustment cannot be fully replayed here;
those are checked by grading against the student's own figures instead.
"""

from __future__ import annotations

from datetime import date

from ..ledger import engine
from ..ledger.models import (
    ADJUSTING,
    CLOSING,
    GENERAL,
    REGULAR,
    SUBSIDIARY,
    Account,
    Entry,
    Journal,
    JournalColumn,
    Line,
    Party,
    Posting,
    Snapshot,
)
from . import schema

# Account types closed to Income Summary.
_TEMP_TYPES = frozenset(
    {"revenue", "contra_revenue", "expense", "cost_of_goods_sold", "other_income", "other_expense"}
)
_DIVIDEND_TYPES = frozenset({"dividends", "drawings"})


def _engine_journals(pack: schema.Pack) -> dict[str, Journal]:
    journals: dict[str, Journal] = {}
    for j in pack.journals:
        columns = tuple(
            JournalColumn(
                key=c.key, label=c.label, side=c.side, account_number=c.account,
                posts=c.posts, subsidiary_kind=c.subsidiary_kind,
            )
            for c in j.columns
        )
        journals[j.key] = Journal(
            key=j.key, name=j.name, ref_prefix=j.ref_prefix, kind=j.kind, columns=columns
        )
    return journals


def column_key_for(journal: Journal, account_number: str, side: str) -> str | None:
    """Which column of a special journal a line belongs in. Public: the answer-key
    replay, the key print and the test fixtures all need the same mapping."""
    if journal.kind != "special":
        return None
    for c in journal.columns:
        if c.account_number == account_number and c.side == side:
            return c.key
    for c in journal.columns:  # fall back to an "Other accounts" column of the right side
        if c.account_number is None and c.side == side:
            return c.key
    return None


def general_journal_key(pack: schema.Pack) -> str:
    for j in pack.journals:
        if j.kind == "general":
            return j.key
    return "general"


def build_replay_snapshot(pack: schema.Pack, key: schema.AnswerKey) -> Snapshot:
    accounts = {
        a.number: Account(
            number=a.number, name=a.name, account_type=a.type, normal_balance=a.normal_balance,
            statement_section=a.statement_section, roles=tuple(a.roles),
            subsidiary_kind=a.subsidiary_kind, sort_order=a.sort_order,
        )
        for a in pack.accounts
    }
    parties = {p.code: Party(code=p.code, kind=p.kind, name=p.name) for p in pack.parties}
    journals = _engine_journals(pack)

    ob = pack.opening_balances.get(key.variant)
    opening_account = dict(ob.accounts) if ob else {}
    opening_party = dict(ob.parties) if ob else {}

    when = pack.period.start if isinstance(pack.period.start, date) else date(2026, 12, 1)
    entries: dict[int, Entry] = {}
    next_id = 1

    # Regular entries from the key.
    for exp in key.expected_entries:
        journal = journals.get(exp.journal)
        lines = tuple(
            Line(
                line_no=i,
                account_number=line.account,
                debit_cents=line.debit or 0,
                credit_cents=line.credit or 0,
                column_key=column_key_for(journal, line.account,
                                       "debit" if line.debit else "credit") if journal else None,
                party_code=line.party,
            )
            for i, line in enumerate(exp.lines, start=1)
        )
        entries[next_id] = Entry(
            id=next_id, journal_key=exp.journal, entry_date=when, kind=REGULAR,
            lines=lines, document_ref=exp.document,
        )
        next_id += 1

    # Independent adjustments (general journal).
    gj = general_journal_key(pack)
    for adj in key.adjustments:
        if adj.amount_basis != "independent" or adj.amount is None:
            continue
        lines = tuple(
            Line(
                line_no=i,
                account_number=pat.account,
                debit_cents=adj.amount if pat.side == "debit" else 0,
                credit_cents=adj.amount if pat.side == "credit" else 0,
            )
            for i, pat in enumerate(adj.pattern, start=1)
        )
        entries[next_id] = Entry(
            id=next_id, journal_key=gj, entry_date=when, kind=ADJUSTING, lines=lines
        )
        next_id += 1

    # Post regulars (to general + subsidiary) and adjustments (to general) to derive the
    # adjusted balances the closing entries need.
    general_postings, subsidiary_postings = _postings(journals, entries)
    working = Snapshot(
        accounts=accounts, parties=parties, journals=journals,
        opening_account_cents=opening_account, opening_party_cents=opening_party,
        entries=entries, general_postings=general_postings,
        subsidiary_postings=subsidiary_postings,
    )
    adjusted = engine.balances(working, "adjusted")

    # Closing entries.
    for lines in closing_line_sets(pack, accounts, adjusted):
        entries[next_id] = Entry(
            id=next_id, journal_key=gj, entry_date=when, kind=CLOSING,
            lines=tuple(lines),
        )
        next_id += 1

    general_postings, subsidiary_postings = _postings(journals, entries)
    return Snapshot(
        accounts=accounts, parties=parties, journals=journals,
        opening_account_cents=opening_account, opening_party_cents=opening_party,
        entries=entries, general_postings=general_postings,
        subsidiary_postings=subsidiary_postings,
    )


def _postings(
    journals: dict[str, Journal], entries: dict[int, Entry]
) -> tuple[tuple[Posting, ...], tuple[Posting, ...]]:
    by_journal: dict[str, list[int]] = {}
    for eid, e in entries.items():
        by_journal.setdefault(e.journal_key, []).append(eid)

    general: list[Posting] = []
    subsidiary: list[Posting] = []
    ordinal = 0
    for jkey, eids in by_journal.items():
        ordinal += 1
        general.append(Posting(journal_key=jkey, target=GENERAL, ordinal=ordinal,
                               entry_ids=tuple(eids)))
        # Subsidiary postings only where lines carry a party.
        party_eids = [
            eid for eid in eids if any(line.party_code for line in entries[eid].lines)
        ]
        if party_eids:
            subsidiary.append(Posting(journal_key=jkey, target=SUBSIDIARY, ordinal=ordinal,
                                     entry_ids=tuple(party_eids)))
    return tuple(general), tuple(subsidiary)


def closing_line_sets(
    pack: schema.Pack, accounts: dict[str, Account], adjusted: dict[str, int]
) -> list[list[Line]]:
    income_summary = next(
        (a.number for a in accounts.values() if "income_summary" in a.roles), None
    )
    retained = next(
        (a.number for a in accounts.values() if "retained_earnings" in a.roles), None
    )
    if income_summary is None or retained is None:
        return []

    sets: list[list[Line]] = []

    # 1) Close temporary (revenue/expense) accounts to Income Summary.
    temp_lines: list[Line] = []
    total_temp = 0
    line_no = 1
    for number, acct in accounts.items():
        if acct.account_type not in _TEMP_TYPES:
            continue
        bal = adjusted.get(number, 0)
        if bal == 0:
            continue
        total_temp += bal
        # Zero the account with a line on the opposite side.
        temp_lines.append(_zeroing_line(line_no, number, bal))
        line_no += 1
    if temp_lines:
        temp_lines.append(_balance_to(line_no, income_summary, total_temp))
        sets.append(temp_lines)

    # 2) Close Income Summary to retained earnings.
    if total_temp != 0:
        sets.append([
            _zeroing_line(1, income_summary, total_temp),
            _balance_to(2, retained, total_temp),
        ])

    # 3) Close dividends/drawings straight to retained earnings.
    for number, acct in accounts.items():
        if acct.account_type not in _DIVIDEND_TYPES:
            continue
        bal = adjusted.get(number, 0)
        if bal == 0:
            continue
        sets.append([
            _zeroing_line(1, number, bal),
            _balance_to(2, retained, bal),
        ])

    return sets


def _zeroing_line(line_no: int, number: str, balance: int) -> Line:
    """A line that brings a debit-positive ``balance`` to zero (opposite side)."""
    if balance > 0:
        return Line(line_no=line_no, account_number=number, credit_cents=balance)
    return Line(line_no=line_no, account_number=number, debit_cents=-balance)


def _balance_to(line_no: int, number: str, total: int) -> Line:
    """The offsetting line that carries ``total`` (debit-positive) onto ``number``."""
    if total > 0:
        return Line(line_no=line_no, account_number=number, debit_cents=total)
    return Line(line_no=line_no, account_number=number, credit_cents=-total)
