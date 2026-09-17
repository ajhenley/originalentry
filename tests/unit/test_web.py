"""Student screens: routing/auth guards and template rendering.

Templates are rendered with a hand-built context and a real engine snapshot (no database), which
also gives a partial A7 check over the student interface.
"""

import re
import types

import pytest
from flask import g, render_template
from parchment.app import create_app
from parchment.ledger import subsidiary_proof, trial_balance
from parchment.ledger.engine import TrialBalanceRow
from parchment.packs import replay, schema
from parchment.presentation import Company, kind_label

from tests.packs import testco_alpha

BANNED = re.compile(r"\b(correct|incorrect|right|wrong)\b", re.IGNORECASE)


@pytest.fixture(scope="module")
def app():
    return create_app()


@pytest.fixture(scope="module")
def snapshot():
    pack = schema.load_pack(testco_alpha.PACK)
    key = schema.load_answer_key(testco_alpha.KEY_A)
    return replay.build_replay_snapshot(pack, key)


def _company():
    return Company(
        slug="testco-alpha", name="TestCo Alpha", accent_hex="#1F5F8B", monogram="TA",
        period_label="December 2026", subsidiary_kinds=("customer",),
    )


def _visible_text(html: str) -> str:
    """Strip tags (so class/aria attributes are ignored) and collapse whitespace (A7)."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def _render_workspace(app, path, template, **ctx):
    with app.test_request_context(path):
        g.workspace = types.SimpleNamespace(public_id="ws12345678", status="in_progress")
        g.company = _company()
        g.read_only = False
        g.read_only_message = None
        return render_template(template, **ctx)


# ── routing / auth ──────────────────────────────────────────────────────────────────────

def test_home_requires_sign_in(app):
    resp = app.test_client().get("/")
    assert resp.status_code == 302
    assert "/auth/sign-in" in resp.headers["Location"]


def test_sign_in_page_renders(app):
    resp = app.test_client().get("/auth/sign-in")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Sign in" in body
    assert not BANNED.search(_visible_text(body))


# ── template rendering + A7 ─────────────────────────────────────────────────────────────

def test_overview_renders_company_chrome(app):
    html = _render_workspace(app, "/w/ws12345678/testco-alpha/", "student/overview.html")
    text = _visible_text(html)
    assert "TestCo Alpha" in text
    assert "December 2026" in text
    assert "TA" in text  # monogram
    assert not BANNED.search(text)


def test_trial_balance_renders_and_balances(app, snapshot):
    tb = trial_balance(snapshot, "adjusted")
    assert tb.in_balance
    html = _render_workspace(
        app, "/w/ws12345678/testco-alpha/trial-balance", "student/trial_balance.html",
        tb=tb, stage="adjusted", stage_label="Adjusted",
        stages=[{"key": "unadjusted", "label": "Unadjusted"},
                {"key": "adjusted", "label": "Adjusted"},
                {"key": "post_closing", "label": "Post-closing"}],
    )
    text = _visible_text(html)
    assert "In balance" in text
    assert "5,000.00" in text  # Accounts Receivable adjusted balance
    assert not BANNED.search(text)


def test_general_ledger_renders(app, snapshot):
    from parchment.ledger import balances

    bals = balances(snapshot, "adjusted")
    rows = [
        TrialBalanceRow(n, snapshot.accounts[n].name, b if b > 0 else 0, -b if b < 0 else 0,
                        snapshot.accounts[n].sort_order)
        for n, b in bals.items() if b != 0
    ]
    html = _render_workspace(
        app, "/w/ws12345678/testco-alpha/ledgers/general", "student/ledger_general.html", rows=rows
    )
    text = _visible_text(html)
    assert "General ledger" in text
    assert not BANNED.search(text)


def test_documents_queue_renders(app):
    from datetime import date

    docs = [
        {"ref": "INV-1", "display_ref": "Invoice 1", "doc_type": "sales_invoice",
         "date": date(2026, 12, 2), "guided": True, "status": None, "reason": None},
        {"ref": "INV-2", "display_ref": "Invoice 2", "doc_type": "sales_invoice",
         "date": date(2026, 12, 5), "guided": False, "status": "record", "reason": None},
    ]
    html = _render_workspace(app, "/w/ws12345678/testco-alpha/documents",
                             "student/documents.html", documents=docs, triaged=1, total=2)
    text = _visible_text(html)
    assert "Invoice 1" in text and "Not handled" in text and "Recorded" in text
    assert not BANNED.search(text)


def test_document_detail_renders_view_as_text(app):
    from datetime import date

    doc = types.SimpleNamespace(
        ref="INV-1", display_ref="Invoice 1", doc_type="sales_invoice",
        doc_date=date(2026, 12, 2), guided=True,
    )
    text_alt = {"fields": [["Customer", "Firstborn Supply"]],
                "lines": [["12", "Kayak rack", "140.00", "1,680.00"]]}
    html = _render_workspace(
        app, "/w/ws12345678/testco-alpha/documents/INV-1", "student/document.html",
        doc=doc, guidance="Sales on account are recorded in the sales journal.",
        alt_text="Sales invoice 1", text_alt=text_alt, disposition=None,
    )
    text = _visible_text(html)
    assert "Firstborn Supply" in text
    assert "Kayak rack" in text
    assert "No entry required" in text
    assert not BANNED.search(text)


def test_checkpoints_render(app):
    from parchment.services.checkpoints import CheckpointState

    checkpoints = [
        {"key": "cp1", "ordinal": 1, "prompt": "Accounts Receivable balance after posting",
         "state": CheckpointState("cp1", 1, False, 2, False)},
        {"key": "cp2", "ordinal": 2, "prompt": "Cash balance",
         "state": CheckpointState("cp2", 3, False, 0, True)},
    ]
    html = _render_workspace(app, "/w/ws12345678/testco-alpha/checkpoints",
                             "student/checkpoints.html", checkpoints=checkpoints)
    text = _visible_text(html)
    assert "Accounts Receivable balance after posting" in text
    assert "locked" in text.lower()
    assert "2 attempts remain" in text
    assert not BANNED.search(text)


def test_submit_page_renders(app):
    html = _render_workspace(app, "/w/ws12345678/testco-alpha/submit", "student/submit.html",
                             triaged=2, total=2, entry_count=3, statements_started=1,
                             statements_total=2, submitted=False)
    text = _visible_text(html)
    assert "Submit my work" in text
    assert "2 of 2" in text
    assert not BANNED.search(text)


def test_subsidiary_proof_renders(app, snapshot):
    proof = subsidiary_proof(snapshot, "customer")
    assert proof.agrees
    html = _render_workspace(
        app, "/w/ws12345678/testco-alpha/ledgers/customer", "student/subsidiary.html",
        kind="customer", kind_label_value=kind_label("customer"), proof=proof,
    )
    text = _visible_text(html)
    assert "Agrees" in text
    assert "Firstborn Supply" in text
    assert not BANNED.search(text)


def test_statements_index_lists_the_forms_the_pack_supplies(app):
    statements = [
        {"type": "income_statement", "title": "Income Statement", "row_count": 4},
        {"type": "balance_sheet", "title": "Balance Sheet", "row_count": 0},
    ]
    html = _render_workspace(app, "/w/ws12345678/testco-alpha/statements",
                             "student/statements.html", statements=statements)
    text = _visible_text(html)
    assert "Income Statement" in text
    assert "Balance Sheet" in text
    assert "Not started" in text  # the balance sheet has no rows yet
    assert not BANNED.search(text)


def test_statement_builder_offers_the_pack_vocabulary_and_the_students_own_figures(app, snapshot):
    from parchment.ledger import balances

    statement = {
        "type": "income_statement", "title": "Income Statement",
        "subtotal_types": [{"key": "net_sales", "label": "Net sales"},
                           {"key": "net_income", "label": "Net income"}],
    }
    rows = [
        {"kind": "heading", "label": "Revenue", "account_number": None, "subtotal_type": None,
         "amount": "", "indent": 0, "amount_column": 1},
        {"kind": "account", "label": None, "account_number": "401", "subtotal_type": None,
         "amount": "5,000.00", "indent": 1, "amount_column": 1},
    ]
    figures = [
        {"number": n, "name": snapshot.accounts[n].name, "amount_cents": b}
        for n, b in balances(snapshot, "adjusted").items() if b != 0
    ]
    accounts = [{"number": n, "name": a.name} for n, a in snapshot.accounts.items()]

    html = _render_workspace(
        app, "/w/ws12345678/testco-alpha/statements/income_statement",
        "student/statement.html",
        statement=statement, rows=rows, accounts=accounts, figures=figures,
        header={"title": "Income Statement"}, blank_rows=3, errors={},
    )
    text = _visible_text(html)
    assert "Income Statement" in text
    assert "Net income" in text          # the pack's subtotal vocabulary is offered
    assert "Sales Revenue" in text       # the account list
    assert "5,000.00" in text            # the student's own adjusted figure, in the side panel
    assert "Add rows" in text
    assert not BANNED.search(text)


def test_statement_builder_shows_a_refusal_next_to_the_row(app):
    statement = {"type": "income_statement", "title": "Income Statement",
                 "subtotal_types": [{"key": "net_income", "label": "Net income"}]}
    rows = [{"kind": "subtotal", "label": None, "account_number": None, "subtotal_type": None,
             "amount": "1.234", "indent": 0, "amount_column": 1}]
    html = _render_workspace(
        app, "/w/ws12345678/testco-alpha/statements/income_statement",
        "student/statement.html",
        statement=statement, rows=rows, accounts=[], figures=[],
        header={"title": "Income Statement"}, blank_rows=1,
        errors={"row-0-subtotal_type": "Choose what this subtotal is."},
    )
    text = _visible_text(html)
    assert "Choose what this subtotal is." in text
    assert not BANNED.search(text)
