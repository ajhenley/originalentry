"""The real company: Riverbend Bicycle Supply, 1-15 December.

The paper practice set is the source of truth, and `scripts/build_pack.py` only translates
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
    """The document count moved to test_the_pack_holds_every_printed_artefact below, which is
    where the envelope's own 62 are counted. The month itself — 28 transactions, 42 accounts,
    five journals — is what this still holds, and none of it changed with the documents."""
    pack = schema.load_pack(generated.pack)

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
    thing marked. The 34 that need none are the envelope's own filed artefacts — the orders, the
    bills of lading, the receiving reports, the time cards, the vouchers and the void cheque —
    not three the profile invented. Checked on version B because
    test_the_pack_holds_every_printed_artefact counts version A, and a count that held for one
    version only would be a pack whose triage differs by version."""
    triage = generated.keys["B"]["triage"]

    assert sum(1 for needed in triage.values() if needed) == 28
    assert sum(1 for needed in triage.values() if not needed) == 34


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


@pytest.mark.parametrize("version", ["A", "B", "C"])
def test_every_cash_document_prints_the_figure_the_key_expects(generated, version):
    """The figure a student must enter has to be legible on the document they enter it from.

    Replaces the two profile-level cross-checks deleted with extra_fields' remittance and
    credit-memo branches (see tests/unit/test_profile_checks.py's note). Those compared one
    hardcoded literal in the profile against the model; this compares the artefact's own printed
    words against the committed answer key, which is the disagreement that would actually reach a
    student -- and it covers every cash document rather than the two that happened to carry
    literals. D23 is the sharp one: its remittance advice prints 4,390.40 after deducting a 2%
    the customer had not earned, and the key expects exactly that cash and no sales discount.

    Scoped to the cash line because that is the figure the paper always states on its face: a
    cheque stub's AMOUNT, a register tape's TOTAL, a remittance's Remitted. The accrual side of a
    sale is a Total on an item table and is covered by
    test_every_entered_document_carries_its_own_amount.
    """
    text = {d["ref"]: json.dumps(d["variants"][version]["text_alternative"])
            for d in json.loads(SOURCE.read_text())["documents"]}
    checked = []
    for entry in generated.keys[version]["expected_entries"]:
        cash = [line for line in entry["lines"] if line["account"] == "101"]
        if not cash:
            continue
        amount = cash[0].get("debit") or cash[0].get("credit")
        printed = f"{amount / 100:,.2f}"
        assert printed in text[entry["document"]], (
            f"{entry['document']} does not print {printed}, which the key expects as its cash"
        )
        checked.append(entry["document"])

    # Without this the test would pass on a key that had stopped naming any cash document at all.
    assert len(checked) == 16, checked


def test_the_subsidiary_ledgers_are_wired(generated):
    pack = schema.load_pack(generated.pack)
    controls = {a.number: a.subsidiary_kind for a in pack.accounts if a.subsidiary_kind}

    assert controls == {"105": "customer", "201": "supplier"}


# ── A document has to be enough to work from ────────────────────────────────────────────
#
# The first cut of the converter carried only the item lines, so a rent cheque reached the
# student as a date and a cheque number with no payee and no amount. It cannot be journalised,
# and nothing in the pack rules would have caught it: it is a perfectly valid pack.
#
# test_every_document_says_how_much_without_saying_what_happened used to stand here and both of
# its halves have moved, because neither is true of an artefact's own words. It required an
# "Amount" field label on every document: that label was the translator's, written by
# _face_amount, and a photographed document prints its figure the way the paper prints it —
# "AMOUNT 7,781.40" with no label on a cheque stub, a Total row on an invoice, nothing at all on
# a time card. tests/unit/test_no_transaction_list.py's
# test_every_entered_document_carries_its_own_amount is the assertion that survived the move: it
# accepts any of the three forms, and it is scoped to the documents triage says take an entry,
# which an envelope full of filed artefacts made necessary. The Description half is
# test_no_riverbend_document_carries_a_description_row in the same file.

@pytest.mark.parametrize("version", ["A", "B", "C"])
def test_the_payroll_register_carries_the_breakdown_the_cheque_cannot(generated, version):
    """The payroll cheque's face value is net pay, which on its own cannot be journalised: the
    entry needs the gross and each withholding separately. The envelope prints them on a
    document of their own — the payroll register — where the summary had to append them to the
    cheque as extra fields.

    Read out of the register's text rather than its field labels, because the register prints
    them as a control total ("FICA withheld 520.20"), not as a labelled row. The figures are
    asserted alongside the words: "FICA withheld" present with the wrong number beside it is the
    failure this has to be able to see, and the words alone could not.
    """
    pack = schema.load_pack(generated.pack)
    register = next(d for d in pack.documents if "payroll" in d.display_ref.lower())
    text = register.variants[version].text_alternative
    said = " ".join(f"{label} {value}" for label, value in text.fields)

    for needed in ("Sales salaries 4,400.00", "Office salaries 2,400.00", "Gross 6,800.00",
                   "FICA withheld 520.20", "Federal 748.00", "State 224.00"):
        assert needed in said, f"{register.display_ref} does not say {needed!r}"
    assert "5,307.80" in said, "the register does not tie to the cheque's net pay"


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
    """Three counter sales all said "Cash register tape". In a list of sixty-two, a label that
    repeats is no label: there is no way to tell which one you have already handled. The envelope
    makes this sharper, not easier — six time cards, five vouchers and five bills of lading all
    share a kind, and an order we sent a supplier has to be tellable from one a customer sent
    us."""
    pack = schema.load_pack(generated.pack)

    labels = [d.display_ref for d in pack.documents]

    assert len(labels) == len(set(labels)), sorted(
        label for label in labels if labels.count(label) > 1)


# ── The instructor copy has to account for every document ───────────────────────────────

def _walkthrough_html(version: str) -> str:
    """Load the generator by path: scripts/ is not a package, and importing it is cheaper and
    more honest than asserting against a rendered PDF."""
    import importlib.util

    path = Path(__file__).resolve().parents[2] / "scripts" / "build_walkthrough.py"
    spec = importlib.util.spec_from_file_location("build_walkthrough", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    src = json.loads(SOURCE.read_text())
    return module.build_html(src, version, build(src).keys[version])


@pytest.mark.parametrize("version", ["A", "B", "C"])
def test_the_instructor_copy_accounts_for_every_document(version):
    """A document missing from the schedule cannot be told from one the converter dropped. The
    three that need no entry were simply absent, which is the same thing as being lost."""
    html = _walkthrough_html(version)
    src = json.loads(SOURCE.read_text())

    for document in src["documents"]:
        assert document["display_ref"] in html, document["display_ref"]


def test_the_no_entry_documents_say_so_and_say_why():
    """Thirty-four of them now, and the instructor has to be able to defend each one. The nine
    authored sentences are named individually rather than counted, because "nine sentences
    appear" would pass if one kind's sentence had been dropped and another's printed twice.

    Loaded from the profile rather than quoted here, because the sentence a reader of this test
    needs is the one the profile actually authored; what makes the assertion falsifiable is that
    the walkthrough builds this html from the committed pack's triage_reasons, which the builder
    expanded from kind to ref, and a kind that stopped resolving would vanish from the html with
    FILED_REASONS unchanged.
    """
    import importlib.util

    html = _walkthrough_html("B")
    spec = importlib.util.spec_from_file_location(
        "riverbend_profile_for_walkthrough",
        Path(__file__).resolve().parents[2] / "packs" / "riverbend" / "profile.py")
    profile = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(profile)

    assert html.count("no entry required") == 34
    assert len(profile.FILED_REASONS) == 9
    for kind, sentence in profile.FILED_REASONS.items():
        assert sentence in html, kind


# ── The envelope, not one summary per transaction ────────────────────────────────────────

def test_the_pack_holds_every_printed_artefact(generated):
    """31 summary documents became 62 printed ones: the envelope's own artefacts, not one
    document per transaction. 28 evidence a transaction and 34 need no entry, so filing is the
    majority judgement rather than a token three."""
    pack = schema.load_pack(generated.pack)

    assert len(pack.documents) == 62
    triage = generated.keys["A"]["triage"]
    assert sum(triage.values()) == 28
    assert len(triage) - sum(triage.values()) == 34


def test_every_filed_document_has_a_reason(generated):
    """V17 requires one per document; Task 4 authors nine by kind and the builder expands.

    The filed set is counted before it is walked. Without that, the loop body never runs on a
    pack that files nothing and the test passes having asserted nothing at all — which is not
    hypothetical: dropping the envelope's filed artefacts in build_pack.py is a one-line change,
    it leaves a pack that still validates, and it made the first draft of this test green while
    breaking the three around it.
    """
    for code, key in generated.keys.items():
        filed = [ref for ref, needs_entry in key["triage"].items() if not needs_entry]
        assert len(filed) == 34, f"{code} files {len(filed)}, so this test proves nothing"
        for ref in filed:
            assert key["triage_reasons"].get(ref, "").strip(), f"{code}: {ref}"


def test_the_receiving_trap_is_two_documents_again(generated):
    """D22 printed Amount 1,748.00 -- the received quantity priced out, which is the answer --
    above a line reading 1,840.00. In the envelope the invoice bills 1,840.00 and a separate
    receiving report records 38 received, so comparing them is the student's work."""
    pack = schema.load_pack(generated.pack)
    text = {d.ref: json.dumps(d.variants["A"].text_alternative.model_dump())
            for d in pack.documents}

    assert "1,840.00" in text["D22-2"]
    assert "1,748.00" not in " ".join(text.values())
    assert "38" in text["D22-3"]
