"""Recording in a special journal through its column grid (T6.1). A filled cell becomes a line
carrying its column_key, so posting derives the column totals the engine expects — the sale reaches
the AR control and, per party, the subsidiary ledger.
"""

import copy
import secrets

import pytest
from parchment.ledger import balances, subsidiary_proof
from parchment.ledger.snapshot import load_snapshot
from parchment.models import EntryLine, JournalEntry, Section, User
from parchment.packs import schema
from parchment.packs.importer import import_content
from parchment.services import workspace_write
from parchment.services.assignments import create_assignment, open_workspace
from parchment.services.posting import post_journal_general, post_journal_subsidiary_all
from sqlalchemy import select

from tests.packs import testco_alpha

pytestmark = pytest.mark.db


def _seed(session):
    data = copy.deepcopy(testco_alpha.PACK)
    slug = f"sj-{secrets.token_hex(3)}"
    data["company"]["slug"] = slug
    pv = import_content(session, schema.load_pack(data), source_sha256=secrets.token_hex(32))
    section = Section(name="Sec", join_code=f"J{secrets.token_hex(3).upper()}")
    student = User(email=f"sj-{secrets.token_hex(3)}@example.edu", role="student")
    session.add_all([section, student])
    session.flush()
    assignment = create_assignment(session, section=section, title="Dec", pack_version=pv)
    ws = open_workspace(session, assignment, student)
    return slug, student, ws


def test_special_form_records_column_keys_and_posts(client, session):
    slug, student, ws = _seed(session)
    client.sign_in(student)
    base = f"/w/{ws.public_id}/{slug}/journals/sales"

    page = client.get(f"{base}/entries/new")
    assert page.status_code == 200
    assert "Columns" in page.get_data(as_text=True)  # the column grid, not the line grid

    resp = client.post(f"{base}/entries/new", data={
        "entry_date": "2026-12-02", "document_ref": "INV-1", "client_key": "sale-1",
        "workspace_version": ws.version,
        "col-ar_dr-amount": "1,200.00", "col-ar_dr-party": "C-ONE",
        "col-sales_cr-amount": "1,200.00",
    })
    assert resp.status_code == 302  # recorded, redirect back to the journal (PRG)

    entry = session.scalars(
        select(JournalEntry).where(JournalEntry.workspace_id == ws.id)
    ).one()
    lines = session.scalars(select(EntryLine).where(EntryLine.entry_id == entry.id)).all()
    assert {line.column_key for line in lines} == {"ar_dr", "sales_cr"}

    # Post to the general and subsidiary ledgers, then the engine derives the column totals.
    workspace_write(session, ws.public_id, student, activity_kind="post",
                    mutate=lambda s, w: post_journal_general(s, w, "sales"))
    workspace_write(session, ws.public_id, student, activity_kind="post",
                    mutate=lambda s, w: post_journal_subsidiary_all(s, w, "sales"))

    snap = load_snapshot(session, ws)
    # AR opening 3,000.00 + this 1,200.00 sale = 4,200.00.
    assert balances(snap, "unadjusted")["112"] == 420000
    proof = subsidiary_proof(snap, "customer")
    assert proof.agrees
    assert {r.party_code: r.balance_cents for r in proof.party_rows}["C-ONE"] == 420000
