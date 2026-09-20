"""The real company: Riverbend Bicycle Supply, 1-15 December.

The paper practice set is the source of truth, and `scripts/build_riverbend.py` only translates
it. What this guards is that the translation stayed faithful: the figures the app derives by
replaying the key through its own ledger engine must equal the figures printed in the
instructor's solution set, to the cent, for all three versions.

If those ever disagree, a student marked by this app and a student marked from the printed key
would receive different marks for the same work, which is the one outcome nobody could defend.
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest
from originalentry.generator import build
from originalentry.packs import schema
from originalentry.packs.validate import validate_pack, warn_pack

SOURCE = Path(__file__).resolve().parents[2] / "packs" / "riverbend" / "source.json"

# Straight from the practice set's own "Checkpoint Answers - All three versions" page.
PAPER = {
    "A": {"cash": Decimal("22295.60"), "trial_balance": Decimal("985315.40")},
    "B": {"cash": Decimal("22413.20"), "trial_balance": Decimal("985769.40")},
    "C": {"cash": Decimal("22530.80"), "trial_balance": Decimal("986223.40")},
}


@pytest.fixture(scope="module")
def generated():
    return build(json.loads(SOURCE.read_text()))


def test_the_source_is_where_the_importer_looks():
    assert SOURCE.exists()


def test_it_builds_a_pack_the_app_would_accept(generated):
    pack = schema.load_pack(generated.pack)
    keys = {code: schema.load_answer_key(k) for code, k in generated.keys.items()}

    assert sorted(keys) == ["A", "B", "C"]
    assert not list(validate_pack(pack, keys))
    assert not list(warn_pack(pack))


def test_it_carries_the_whole_month(generated):
    pack = schema.load_pack(generated.pack)

    # 28 transactions, plus the three that arrive and need nothing doing with them.
    assert len(pack.documents) == 31
    assert len(generated.keys["B"]["expected_entries"]) == 28
    assert len(pack.accounts) == 42
    assert {j.key for j in pack.journals} == {
        "sales", "purchases", "cash_receipts", "cash_payments", "general"}


@pytest.mark.parametrize("version", ["A", "B", "C"])
def test_the_cash_balance_matches_the_printed_key(generated, version):
    """Checkpoint 2 on the paper set: cash at 15 December."""
    cash = Decimal(generated.keys[version]["checkpoints"]["cp2"]) / 100

    assert cash == PAPER[version]["cash"]


@pytest.mark.parametrize("version", ["A", "B", "C"])
def test_the_trial_balance_matches_the_printed_key(generated, version):
    balances = generated.keys[version]["expected_balances"]["adjusted"]

    total = Decimal(sum(v for v in balances.values() if v > 0)) / 100

    assert total == PAPER[version]["trial_balance"]


@pytest.mark.parametrize("version", ["A", "B", "C"])
def test_the_books_balance(generated, version):
    balances = generated.keys[version]["expected_balances"]["adjusted"]

    assert sum(balances.values()) == 0


def test_the_versions_really_do_differ(generated):
    """A student working from a classmate's figures should fail checkpoint 1 immediately."""
    cash = {v: generated.keys[v]["checkpoints"]["cp2"] for v in ("A", "B", "C")}

    assert len(set(cash.values())) == 3


def test_triage_is_a_real_judgement(generated):
    """With every document needing an entry there is nothing to judge, and triage is the first
    thing marked. The three that need none come from the paper set's own no-entry documents."""
    triage = generated.keys["B"]["triage"]

    assert sum(1 for needed in triage.values() if needed) == 28
    assert sum(1 for needed in triage.values() if not needed) == 3


def test_the_cost_of_every_item_is_reachable(generated):
    """A sales invoice shows what the customer pays. Cost of goods sold needs the cost, which is
    nowhere on the document, so the pack has to carry it or half the sales cannot be recorded."""
    pack = schema.load_pack(generated.pack)
    inventory = next(s for s in pack.reference if s.key == "inventory")
    table = next(b for b in inventory.blocks if b["type"] == "table")

    listed = {row[0] for row in table["rows"]}
    assert listed == {"S-01", "S-02", "S-03", "S-04", "S-05", "S-06", "S-07", "S-08", "S-09"}
    assert "Our cost" in table["headers"]


def test_every_designed_error_is_named(generated):
    """The five traps the practice set builds in, each recognised on its own document."""
    signatures = generated.keys["B"]["error_signatures"]

    assert {s["key"] for s in signatures} == {
        "freight", "receiving", "shortpay", "purchdisc", "earlydisc"}
    for signature in signatures:
        assert signature["detect"]["document"], signature["key"]


def test_the_subsidiary_ledgers_are_wired(generated):
    pack = schema.load_pack(generated.pack)
    controls = {a.number: a.subsidiary_kind for a in pack.accounts if a.subsidiary_kind}

    assert controls == {"105": "customer", "201": "supplier"}


# ── A document has to be enough to work from ────────────────────────────────────────────
#
# The first cut of the converter carried only the item lines, so a rent cheque reached the
# student as a date and a cheque number with no payee and no amount. It cannot be journalised,
# and nothing in the pack rules would have caught it: it is a perfectly valid pack.

@pytest.mark.parametrize("version", ["A", "B", "C"])
def test_every_document_says_what_it_is_for_and_how_much(generated, version):
    pack = schema.load_pack(generated.pack)

    for document in pack.documents:
        text = document.variants[version].text_alternative
        labels = {label for label, _ in text.fields}
        assert "Amount" in labels, f"{document.display_ref} carries no amount"
        assert "Description" in labels, f"{document.display_ref} says nothing about itself"


@pytest.mark.parametrize("version", ["A", "B", "C"])
def test_the_payroll_cheque_carries_its_breakdown(generated, version):
    """Its face value is net pay, which on its own cannot be journalised: the entry needs the
    gross, and each withholding separately."""
    pack = schema.load_pack(generated.pack)
    payroll = next(d for d in pack.documents if "payroll" in d.display_ref.lower())

    labels = {label for label, _ in payroll.variants[version].text_alternative.fields}

    for needed in ("Gross pay", "FICA withheld", "Federal income tax withheld",
                   "State income tax withheld"):
        assert needed in labels, needed


def test_a_document_never_carries_the_authors_note(generated):
    """The model's notes say things like "TRAP: freight-in capitalises into Inventory". They are
    for the instructor and must never reach the paper."""
    pack = schema.load_pack(generated.pack)

    for document in pack.documents:
        for version in ("A", "B", "C"):
            text = document.variants[version].text_alternative
            blob = " ".join(v for _, v in text.fields) + " ".join(
                " ".join(line) for line in text.lines)
            assert "TRAP" not in blob.upper(), document.display_ref


def test_no_two_documents_look_the_same_in_the_list(generated):
    """Three counter sales all said "Cash register tape". In a list of thirty-one, a label that
    repeats is no label: there is no way to tell which one you have already handled."""
    pack = schema.load_pack(generated.pack)

    labels = [d.display_ref for d in pack.documents]

    assert len(labels) == len(set(labels)), sorted(
        label for label in labels if labels.count(label) > 1)
