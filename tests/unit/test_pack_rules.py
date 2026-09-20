"""The validation rules a pack must pass before anyone marks a section with it (T5.4).

V5, V8 and V11 are the ones that catch an authoring slip the replay alone would not: a chart with
no retained-earnings account, an entry a journal's columns cannot hold, and a key whose own
entries would be reported as a designed error.
"""

import copy

from originalentry.packs import schema, validate
from originalentry.packs.validate import validate_pack

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


# ── W1: the four words, in the pack's own text ──────────────────────────────────────────
#
# The app never tells a student they are wrong (A7), and a guard keeps those words out of the
# templates and the scripts. None of that helps if a company's own documents say it — so the
# author is warned before the pack is ever in front of anyone.
#
# It is a warning, not a refusal. "Correct" has honest uses in accounting prose ("a correcting
# entry"), and the author is the one who can tell.

def _pack_with(text_at: str, value: str) -> dict:
    data = copy.deepcopy(testco_alpha.PACK)
    node = data
    parts = text_at.split(".")
    for part in parts[:-1]:
        if part.isdigit():
            node = node[int(part)]
        else:
            node = node[part]
    node[parts[-1]] = value
    return data


def test_a_clean_pack_raises_no_warning():
    pack = schema.load_pack(testco_alpha.PACK)

    assert list(validate.warn_pack(pack)) == []


def test_guidance_that_says_correct_is_warned_about():
    pack = schema.load_pack(_pack_with("documents.0.guidance", "Choose the correct journal."))

    warnings = list(validate.warn_pack(pack))

    assert [w.rule for w in warnings] == ["W1"]
    assert "documents" in warnings[0].path


def test_each_of_the_four_words_is_caught():
    for word in ("correct", "incorrect", "right", "wrong"):
        pack = schema.load_pack(_pack_with("documents.0.guidance", f"That is {word}."))

        assert [w.rule for w in validate.warn_pack(pack)] == ["W1"], word


def test_a_word_that_merely_contains_one_is_left_alone():
    """"Copyright" is not "right"."""
    pack = schema.load_pack(_pack_with("documents.0.guidance", "Copyright of the supplier."))

    assert list(validate.warn_pack(pack)) == []


def test_a_checkpoint_prompt_is_read_too():
    pack = schema.load_pack(_pack_with("checkpoints.0.prompt", "Enter the correct balance"))

    warnings = list(validate.warn_pack(pack))

    assert [w.rule for w in warnings] == ["W1"]
    assert "checkpoints" in warnings[0].path


def test_the_warning_says_which_word_and_where():
    pack = schema.load_pack(_pack_with("documents.0.guidance", "Choose the correct journal."))

    warning = list(validate.warn_pack(pack))[0]

    assert "correct" in warning.message
    assert warning.path.endswith("guidance")


def test_a_warning_never_refuses_the_pack():
    """The author decides. A refusal here would make a judgement about their prose."""
    data = _pack_with("documents.0.guidance", "Choose the correct journal.")
    pack = schema.load_pack(data)

    assert list(validate.validate_pack(pack)) == []
    assert list(validate.warn_pack(pack)) != []


def test_the_rule_is_no_longer_listed_as_unwritten():
    assert "W1" not in validate.DEFERRED_RULES
