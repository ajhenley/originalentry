"""The validation rules a pack must pass before anyone marks a section with it (T5.4).

V5, V8 and V11 are the ones that catch an authoring slip the replay alone would not: a chart with
no retained-earnings account, an entry a journal's columns cannot hold, and a key whose own
entries would be reported as a designed error.
"""

import copy

from parchment.packs import schema
from parchment.packs.validate import validate_pack

from tests.packs import testco_alpha


def _problems(pack_dict, key_dict=None, rule=None):
    pack = schema.load_pack(pack_dict)
    keys = {"A": schema.load_answer_key(key_dict)} if key_dict else None
    found = validate_pack(pack, keys)
    return [p for p in found if rule is None or p.rule == rule]


def test_the_fixture_pack_passes_every_rule():
    assert _problems(testco_alpha.PACK, testco_alpha.KEY_A) == []


# ── V5: the roles the engine needs ──────────────────────────────────────────────────────

def test_v5_a_chart_without_retained_earnings_is_refused():
    pack = copy.deepcopy(testco_alpha.PACK)
    for account in pack["accounts"]:
        if "retained_earnings" in account.get("roles", []):
            account["roles"] = []

    problems = _problems(pack, rule="V5")

    assert problems and "retained_earnings" in problems[0].message


def test_v5_a_role_declared_twice_is_refused():
    pack = copy.deepcopy(testco_alpha.PACK)
    pack["accounts"][0]["roles"] = ["income_summary"]

    problems = _problems(pack, rule="V5")

    assert problems and "income_summary" in problems[0].message


def test_v5_customers_need_exactly_one_control_account():
    pack = copy.deepcopy(testco_alpha.PACK)
    for account in pack["accounts"]:
        account.pop("subsidiary_kind", None)

    problems = _problems(pack, rule="V5")

    assert problems and "customer" in problems[0].message


# ── V8: an entry its journal cannot hold ────────────────────────────────────────────────

def test_v8_an_entry_that_does_not_balance_is_refused():
    key = copy.deepcopy(testco_alpha.KEY_A)
    key["expected_entries"][0]["lines"][0]["debit"] = 999

    problems = _problems(testco_alpha.PACK, key, rule="V8")

    assert problems and "balance" in problems[0].message.lower()


def test_v8_a_special_journal_entry_using_an_account_it_has_no_column_for_is_refused():
    key = copy.deepcopy(testco_alpha.KEY_A)
    key["expected_entries"][0]["lines"][1]["account"] = "611"  # the sales journal has no column

    problems = _problems(testco_alpha.PACK, key, rule="V8")

    assert problems and "611" in problems[0].message


def test_v8_the_general_journal_holds_anything():
    key = copy.deepcopy(testco_alpha.KEY_A)
    key["expected_entries"][0]["journal"] = "general"
    key["expected_entries"][0]["lines"][1]["account"] = "611"

    assert _problems(testco_alpha.PACK, key, rule="V8") == []


# ── V11: signatures and adjustments ─────────────────────────────────────────────────────

def test_v11_a_signature_the_key_itself_would_trigger_is_refused():
    """If the key's own entry looks like the designed error, every student is reported for it."""
    key = copy.deepcopy(testco_alpha.KEY_A)
    key["error_signatures"][0]["detect"] = {
        "type": "entry_line", "document": "INV-1", "account": "112", "side": "debit",
    }

    problems = _problems(testco_alpha.PACK, key, rule="V11")

    assert problems and "sale_to_an_expense_account" in problems[0].path


def test_v11_a_signature_on_a_document_the_key_records_nothing_for_is_refused():
    key = copy.deepcopy(testco_alpha.KEY_A)
    key["triage"]["INV-2"] = False
    key["expected_entries"] = [e for e in key["expected_entries"] if e["document"] != "INV-2"]

    problems = _problems(testco_alpha.PACK, key, rule="V11")

    assert any("INV-2" in p.message for p in problems)


def test_v11_an_independent_adjustment_needs_its_figure():
    key = copy.deepcopy(testco_alpha.KEY_A)
    key["adjustments"][0].pop("amount")

    problems = _problems(testco_alpha.PACK, key, rule="V11")

    assert problems and "amount" in problems[0].message


def test_v11_a_dependent_adjustment_needs_the_balance_it_follows_from():
    key = copy.deepcopy(testco_alpha.KEY_A)
    key["adjustments"][0]["amount_basis"] = "dependent"
    key["adjustments"][0].pop("amount")

    problems = _problems(testco_alpha.PACK, key, rule="V11")

    assert problems and "base_account" in problems[0].message
