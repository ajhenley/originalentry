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
