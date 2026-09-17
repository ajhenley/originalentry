"""The write path end to end (T3.4, T6.4): record → post → subsidiary-post → reverse/void, all
through ``workspace_write``, with the ledger derived back through ``snapshot.py``.
"""

from datetime import date

import pytest
from parchment.forms.entries import EntryCommand, LineCommand
from parchment.ledger import balances, subsidiary_proof, trial_balance
from parchment.ledger.snapshot import load_snapshot
from parchment.models import (
    ActivityEvent,
    Assignment,
    JournalEntry,
    Section,
    User,
    Variant,
    Workspace,
)
from parchment.packs import schema
from parchment.packs.importer import import_content
from parchment.services import WriteRefused, workspace_write
from parchment.services.entries import record_entry, void_entry
from parchment.services.posting import (
    post_entry_subsidiary,
    post_journal_general,
    reverse_run,
)
from sqlalchemy import func, select

from tests.packs import testco_alpha

pytestmark = pytest.mark.db


def _seed(session):
    pack = schema.load_pack(testco_alpha.PACK)
    pv = import_content(session, pack, source_sha256="w" * 64)
    variant = session.scalars(select(Variant).where(Variant.pack_version_id == pv.id)).first()
    section = Section(name="Sec", join_code="wp-join")
    student = User(email="wp@example.edu")
    session.add_all([section, student])
    session.flush()
    asg = Assignment(section_id=section.id, title="December", company_policy="fixed",
                     fixed_pack_version_id=pv.id)
    session.add(asg)
    session.flush()
    ws = Workspace(assignment_id=asg.id, student_id=student.id, pack_version_id=pv.id,
                   variant_id=variant.id, status="not_started")
    session.add(ws)
    session.flush()
    return ws, student, pv


def _sale_command(client_key="ck-1"):
    # A credit sale recorded in the general journal: AR (control) + party, Sales credit.
    return EntryCommand(
        journal_key="general", kind="regular", document_ref="INV-1",
        entry_date=date(2026, 12, 2), description="Credit sale",
        lines=[
            LineCommand("112", "C-ONE", 120000, 0),
            LineCommand("401", None, 0, 120000),
        ],
        client_key=client_key,
    )


def test_record_is_idempotent_and_starts_workspace(session):
    ws, student, _ = _seed(session)
    cmd = _sale_command()

    workspace_write(session, ws.public_id, student, activity_kind="save",
                    mutate=lambda s, w: record_entry(s, w, cmd))
    workspace_write(session, ws.public_id, student, activity_kind="save",
                    mutate=lambda s, w: record_entry(s, w, cmd))  # same client_key

    count = session.execute(
        select(func.count()).select_from(JournalEntry).where(JournalEntry.workspace_id == ws.id)
    ).scalar_one()
    assert count == 1  # the repeated client_key did not create a duplicate

    session.refresh(ws)
    assert ws.status == "in_progress" and ws.version >= 1
    events = session.scalars(
        select(ActivityEvent).where(ActivityEvent.workspace_id == ws.id)
    ).all()
    assert any(e.kind == "save" for e in events)


def test_post_flows_to_the_ledger_and_subsidiary(session):
    ws, student, _ = _seed(session)
    workspace_write(session, ws.public_id, student, activity_kind="save",
                    mutate=lambda s, w: record_entry(s, w, _sale_command()))
    entry = session.scalars(
        select(JournalEntry).where(JournalEntry.workspace_id == ws.id)
    ).one()

    # Before posting, nothing is in the ledger.
    snap = load_snapshot(session, ws)
    assert balances(snap, "unadjusted").get("112", 300000) == 300000  # opening only

    workspace_write(session, ws.public_id, student, activity_kind="post",
                    mutate=lambda s, w: post_journal_general(s, w, "general"))
    snap = load_snapshot(session, ws)
    assert balances(snap, "unadjusted")["112"] == 420000  # opening 3,000 + 1,200
    assert trial_balance(snap, "unadjusted").in_balance

    workspace_write(session, ws.public_id, student, activity_kind="post",
                    mutate=lambda s, w: post_entry_subsidiary(s, w, entry.public_id))
    snap = load_snapshot(session, ws)
    proof = subsidiary_proof(snap, "customer")
    assert proof.agrees
    assert {r.party_code: r.balance_cents for r in proof.party_rows}["C-ONE"] == 420000


def test_posted_entry_cannot_be_voided_then_reverse_frees_it(session):
    ws, student, _ = _seed(session)
    workspace_write(session, ws.public_id, student, activity_kind="save",
                    mutate=lambda s, w: record_entry(s, w, _sale_command()))
    entry = session.scalars(
        select(JournalEntry).where(JournalEntry.workspace_id == ws.id)
    ).one()
    run = workspace_write(session, ws.public_id, student, activity_kind="post",
                          mutate=lambda s, w: post_journal_general(s, w, "general"))

    with pytest.raises(WriteRefused):
        workspace_write(session, ws.public_id, student, activity_kind="save",
                        mutate=lambda s, w: void_entry(s, w, entry.public_id, "changed my mind"))

    # Reversing frees the entry; the ledger empties again.
    workspace_write(session, ws.public_id, student, activity_kind="reverse",
                    mutate=lambda s, w: reverse_run(s, w, run.public_id, "re-journalising"))
    snap = load_snapshot(session, ws)
    assert balances(snap, "unadjusted").get("112", 300000) == 300000


def test_double_posting_is_refused(session):
    ws, student, _ = _seed(session)
    workspace_write(session, ws.public_id, student, activity_kind="save",
                    mutate=lambda s, w: record_entry(s, w, _sale_command()))
    workspace_write(session, ws.public_id, student, activity_kind="post",
                    mutate=lambda s, w: post_journal_general(s, w, "general"))
    with pytest.raises(WriteRefused):
        workspace_write(session, ws.public_id, student, activity_kind="post",
                        mutate=lambda s, w: post_journal_general(s, w, "general"))
