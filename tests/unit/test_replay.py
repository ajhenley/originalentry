"""V9 / A2-at-upload: the pure in-memory replay reproduces the key's balances, and a corrupted
expected balance is caught (no database)."""

import copy

from parchment.ledger import engine
from parchment.packs import replay, schema, validate

from tests.packs import testco_alpha


def _rules(problems):
    return {p.rule for p in problems}


def test_replay_reproduces_expected_balances():
    pack = schema.load_pack(testco_alpha.PACK)
    key = schema.load_answer_key(testco_alpha.KEY_A)
    snapshot = replay.build_replay_snapshot(pack, key)

    adjusted = engine.balances(snapshot, "adjusted")
    for number, want in key.expected_balances["adjusted"].items():
        assert adjusted.get(number, 0) == want, f"adjusted {number}"

    post_closing = engine.balances(snapshot, "post_closing")
    for number, want in key.expected_balances["post_closing"].items():
        assert post_closing.get(number, 0) == want, f"post_closing {number}"
    # Temporary accounts closed to zero.
    assert post_closing.get("401", 0) == 0
    assert post_closing.get("611", 0) == 0
    assert post_closing.get("399", 0) == 0


def test_v9_passes_on_valid_pack():
    pack = schema.load_pack(testco_alpha.PACK)
    key = schema.load_answer_key(testco_alpha.KEY_A)
    assert validate.validate_pack(pack, {"A": key}) == []


def test_v9_detects_wrong_expected_balance():
    pack = schema.load_pack(testco_alpha.PACK)
    key_data = copy.deepcopy(testco_alpha.KEY_A)
    key_data["expected_balances"]["adjusted"]["112"] += 1  # off by one cent
    key = schema.load_answer_key(key_data)
    problems = validate.validate_pack(pack, {"A": key})
    assert "V9" in _rules(problems)
