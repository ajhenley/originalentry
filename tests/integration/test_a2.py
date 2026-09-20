"""A2 through the database (V9): import testco-alpha, replay the full December cycle into the
work tables, load it back with ``ledger.snapshot``, and confirm the derived balances, trial
balances and subsidiary proof equal the answer key to the cent.

This is the DB-backed counterpart of the pure engine test. When the form endpoints exist
(phase 2), the same assertions run by driving those endpoints instead of inserting rows.
"""

from datetime import date

import pytest
from originalentry.ledger import snapshot as snap
from originalentry.ledger import trial_balance
from originalentry.ledger.engine import balances, subsidiary_proof
from originalentry.models import (
    Account,
    Assignment,
    EntryLine,
    JournalEntry,
    Party,
    PostingRun,
    PostingRunEntry,
    Section,
    User,
    Variant,
    Workspace,
)
from originalentry.packs import schema, validate
from originalentry.packs.importer import import_content
from sqlalchemy import select

from tests.packs import testco_alpha

pytestmark = pytest.mark.db


def _add_entry(session, ws, pv_id, accounts, parties, *, journal_key, kind, ck, lines):
    entry = JournalEntry(
        workspace_id=ws.id, pack_version_id=pv_id, journal_key=journal_key,
        entry_date=date(2026, 12, 15), kind=kind, client_key=ck,
    )
    session.add(entry)
    session.flush()
    for i, (number, party_code, debit, credit, column_key) in enumerate(lines, start=1):
        session.add(
            EntryLine(
                entry_id=entry.id, workspace_id=ws.id, pack_version_id=pv_id, line_no=i,
                column_key=column_key, account_id=accounts[number],
                party_id=parties[party_code] if party_code else None,
                debit_cents=debit, credit_cents=credit,
            )
        )
    session.flush()
    return entry


def _post(session, ws, *, journal_key, target, ordinal, ck, entries):
    run = PostingRun(
        workspace_id=ws.id, journal_key=journal_key, target=target, ordinal=ordinal, client_key=ck
    )
    session.add(run)
    session.flush()
    for e in entries:
        session.add(
            PostingRunEntry(posting_run_id=run.id, entry_id=e.id, target=target, active=True)
        )
    session.flush()


def test_a2_full_cycle_reproduces_key(session):
    pack = schema.load_pack(testco_alpha.PACK)
    key = schema.load_answer_key(testco_alpha.KEY_A)
    assert validate.validate_pack(pack, {"A": key}) == []

    pv = import_content(session, pack, source_sha256="c" * 64)
    accounts = {
        a.number: a.id
        for a in session.scalars(select(Account).where(Account.pack_version_id == pv.id))
    }
    parties = {
        p.code: p.id
        for p in session.scalars(select(Party).where(Party.pack_version_id == pv.id))
    }
    variant = session.scalars(
        select(Variant).where(Variant.pack_version_id == pv.id, Variant.code == "A")
    ).one()

    section = Section(name="Sec 1", join_code="a2-join")
    student = User(email="a2@example.edu")
    session.add_all([section, student])
    session.flush()
    assignment = Assignment(
        section_id=section.id, title="December", company_policy="fixed",
        fixed_pack_version_id=pv.id,
    )
    session.add(assignment)
    session.flush()
    ws = Workspace(
        assignment_id=assignment.id, student_id=student.id, pack_version_id=pv.id,
        variant_id=variant.id, status="in_progress",
    )
    session.add(ws)
    session.flush()

    # Regular sales entries (special journal — lines carry their column_key).
    e1 = _add_entry(session, ws, pv.id, accounts, parties, journal_key="sales", kind="regular",
                    ck="e1", lines=[("112", "C-ONE", 120000, 0, "ar_dr"),
                                    ("401", None, 0, 120000, "sales_cr")])
    e2 = _add_entry(session, ws, pv.id, accounts, parties, journal_key="sales", kind="regular",
                    ck="e2", lines=[("112", "C-TWO", 80000, 0, "ar_dr"),
                                    ("401", None, 0, 80000, "sales_cr")])
    # Adjusting: depreciation.
    e3 = _add_entry(session, ws, pv.id, accounts, parties, journal_key="general", kind="adjusting",
                    ck="e3", lines=[("611", None, 25000, 0, None),
                                    ("155", None, 0, 25000, None)])
    # Closing: revenue+expense to income summary, then income summary to capital.
    e4 = _add_entry(session, ws, pv.id, accounts, parties, journal_key="general", kind="closing",
                    ck="e4", lines=[("401", None, 200000, 0, None),
                                    ("399", None, 0, 200000, None)])
    e5 = _add_entry(session, ws, pv.id, accounts, parties, journal_key="general", kind="closing",
                    ck="e5", lines=[("399", None, 25000, 0, None),
                                    ("611", None, 0, 25000, None)])
    e6 = _add_entry(session, ws, pv.id, accounts, parties, journal_key="general", kind="closing",
                    ck="e6", lines=[("399", None, 175000, 0, None),
                                    ("301", None, 0, 175000, None)])

    _post(session, ws, journal_key="sales", target="general", ordinal=1, ck="p1", entries=[e1, e2])
    _post(session, ws, journal_key="sales", target="subsidiary", ordinal=1, ck="p2",
          entries=[e1, e2])
    _post(session, ws, journal_key="general", target="general", ordinal=1, ck="p3",
          entries=[e3, e4, e5, e6])

    s = snap.load_snapshot(session, ws)

    # Trial balances balance at every stage (tension 1/2).
    assert trial_balance(s, "unadjusted").in_balance
    assert trial_balance(s, "adjusted").in_balance
    assert trial_balance(s, "post_closing").in_balance

    # Derived balances match the key to the cent (V9).
    adjusted = balances(s, "adjusted")
    for number, expected in key.expected_balances["adjusted"].items():
        assert adjusted.get(number, 0) == expected, f"adjusted {number}"
    post_closing = balances(s, "post_closing")
    for number, expected in key.expected_balances["post_closing"].items():
        assert post_closing.get(number, 0) == expected, f"post_closing {number}"
    # Temporary accounts are zero after closing.
    assert post_closing.get("401", 0) == 0
    assert post_closing.get("611", 0) == 0
    assert post_closing.get("399", 0) == 0

    # Subsidiary proof agrees on the student's own figures.
    proof = subsidiary_proof(s, "customer")
    assert proof.agrees
    assert proof.control_balance_cents == 500000
    assert {r.party_code: r.balance_cents for r in proof.party_rows} == {
        "C-ONE": 420000, "C-TWO": 80000,
    }

    # Checkpoint cp1: AR balance after posting regular entries.
    assert balances(s, "unadjusted")["112"] == key.checkpoints["cp1"]
