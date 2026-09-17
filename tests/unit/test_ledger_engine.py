"""A miniature A2 for the pure engine (T6): replay a small set of entries, post them, and
confirm the derived trial balances and the subsidiary proof to the cent — with no database."""

from datetime import date

import pytest
from parchment import ledger
from parchment.ledger import (
    ADJUSTING,
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


@pytest.fixture
def snap() -> Snapshot:
    accounts = {
        a.number: a
        for a in [
            Account("101", "Cash", "asset", "debit", sort_order=1),
            Account(
                "112", "Accounts Receivable", "asset", "debit",
                roles=("ar_control",), subsidiary_kind="customer", sort_order=2,
            ),
            Account("161", "Accumulated Depreciation", "contra_asset", "credit", sort_order=3),
            Account("300", "Owner Capital", "equity", "credit", sort_order=4),
            Account("401", "Sales Revenue", "revenue", "credit", sort_order=5),
            Account("625", "Depreciation Expense", "expense", "debit", sort_order=6),
        ]
    }
    parties = {
        "C-HALV": Party("C-HALV", "customer", "Halvorsen Outfitters"),
        "C-BEND": Party("C-BEND", "customer", "Bend Retail"),
    }
    sales = Journal(
        key="sales", name="Sales Journal", ref_prefix="S", kind="special",
        columns=(
            JournalColumn("ar_dr", "Accounts Receivable Dr", "debit", "112", "total", "customer"),
            JournalColumn("sales_cr", "Sales Cr", "credit", "401", "total"),
        ),
    )
    general = Journal(key="general", name="General Journal", ref_prefix="J", kind="general")

    entries = {
        1: Entry(
            id=1, journal_key="sales", entry_date=date(2026, 12, 2), kind=REGULAR,
            document_ref="INV-1",
            lines=(
                Line(1, "112", debit_cents=168000, column_key="ar_dr", party_code="C-HALV"),
                Line(2, "401", credit_cents=168000, column_key="sales_cr"),
            ),
        ),
        2: Entry(
            id=2, journal_key="sales", entry_date=date(2026, 12, 5), kind=REGULAR,
            document_ref="INV-2",
            lines=(
                Line(1, "112", debit_cents=100000, column_key="ar_dr", party_code="C-BEND"),
                Line(2, "401", credit_cents=100000, column_key="sales_cr"),
            ),
        ),
        3: Entry(
            id=3, journal_key="general", entry_date=date(2026, 12, 31), kind=ADJUSTING,
            description="Depreciation of equipment",
            lines=(
                Line(1, "625", debit_cents=45000),
                Line(2, "161", credit_cents=45000),
            ),
        ),
    }
    return Snapshot(
        accounts=accounts,
        parties=parties,
        journals={"sales": sales, "general": general},
        # Debit-positive openings; they sum to zero (V6). Party openings tie to the AR
        # control opening (V7): C-HALV 4,200.00 == account 112 opening.
        opening_account_cents={"101": 1_845_000, "112": 420_000, "300": -2_265_000},
        opening_party_cents={"C-HALV": 420_000},
        entries=entries,
        general_postings=(
            Posting("sales", GENERAL, 1, (1, 2)),
            Posting("general", GENERAL, 1, (3,)),
        ),
        subsidiary_postings=(Posting("sales", SUBSIDIARY, 1, (1, 2)),),
    )


def test_special_journal_posts_column_totals(snap):
    gl = ledger.general_ledger(snap)
    # Two total columns from the sales run (one aggregate line each) + two general-journal lines.
    sales_lines = [line for line in gl if line.reference == "S1"]
    assert len(sales_lines) == 2
    ar_total = next(line for line in sales_lines if line.account_number == "112")
    assert ar_total.debit_cents == 268000
    assert ar_total.source_entry_id is None  # a column total, not a single entry
    assert ar_total.date == date(2026, 12, 5)  # latest entry in the run
    assert {line.reference for line in gl if line.journal_key == "general"} == {"J1"}


def test_unadjusted_trial_balance_balances(snap):
    tb = ledger.trial_balance(snap, "unadjusted")
    assert tb.in_balance
    assert tb.difference_cents == 0
    assert tb.total_debit_cents == tb.total_credit_cents == 2_533_000
    # The adjusting accounts have no unadjusted activity, so they do not appear.
    assert {r.account_number for r in tb.rows} == {"101", "112", "300", "401"}


def test_adjusted_trial_balance_includes_adjustments(snap):
    tb = ledger.trial_balance(snap, "adjusted")
    assert tb.in_balance
    assert tb.total_debit_cents == tb.total_credit_cents == 2_578_000
    numbers = {r.account_number for r in tb.rows}
    assert {"625", "161"} <= numbers


def test_subsidiary_proof_agrees(snap):
    proof = ledger.subsidiary_proof(snap, "customer")
    assert proof.control_account_number == "112"
    assert proof.control_balance_cents == 688_000
    assert proof.party_total_cents == 688_000
    assert proof.agrees
    balances_by_party = {r.party_code: r.balance_cents for r in proof.party_rows}
    assert balances_by_party == {"C-HALV": 588_000, "C-BEND": 100_000}


def test_voided_entry_is_not_posted(snap):
    voided = snap.entries[2]
    snap.entries[2] = Entry(
        id=voided.id, journal_key=voided.journal_key, entry_date=voided.entry_date,
        kind=voided.kind, lines=voided.lines, voided=True,
    )
    gl = ledger.general_ledger(snap)
    ar_total = next(line for line in gl if line.reference == "S1" and line.account_number == "112")
    assert ar_total.debit_cents == 168000  # only the non-void entry contributes


def test_account_by_role_not_by_number(snap):
    assert snap.account_by_role("ar_control").number == "112"
    assert snap.account_by_role("missing_role") is None
