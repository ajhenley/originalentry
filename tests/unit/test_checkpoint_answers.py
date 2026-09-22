"""The figure a checkpoint expects is the figure a student would write (T8.3).

A checkpoint asks for a balance in words: "Accounts Payable control balance at 15 December".
Internally a balance is a signed number, debits positive, and a liability therefore carries a
negative one. The key stored that signed number and compared it to the cent, so the only
accepted answer for a liability was negative.

Nobody states a balance that way. A trial balance, a ledger and every textbook put Accounts
Payable in the credit column as a positive figure, and a student who types what they see is
refused with no way to discover why. It happened: one entered 32,520.00 twice.

So the key stores the balance as it is stated, on the account's own normal side. An account
standing on the wrong side of itself, a bank account overdrawn, still reads negative, because
that is how that would be stated too.
"""

import json
from pathlib import Path

import pytest
from originalentry.generator import build

SOURCE = Path(__file__).resolve().parents[2] / "packs" / "riverbend" / "source.json"


@pytest.fixture(scope="module")
def src():
    return json.loads(SOURCE.read_text())


@pytest.fixture(scope="module")
def generated(src):
    return build(src)


@pytest.fixture(scope="module")
def normal_side(src):
    return {a["number"]: a["normal_balance"] for a in src["accounts"]}


@pytest.fixture(scope="module")
def measured(src):
    return {c["key"]: c["measure"]["account"] for c in src["checkpoints"]}


# Stated the way a trial balance states a balance: a positive figure on the account's own side.
# Only cp2 is corroborated against the printed key, by test_riverbend_pack, which checks cash at
# 15 December for all three versions. cp1 and cp3 are this app's own figures, pinned here so a
# change to them has to be deliberate.
STATED = {
    "A": {"cp1": 30994.60, "cp2": 22295.60, "cp3": 32152.00},
    "B": {"cp1": 31144.60, "cp2": 22413.20, "cp3": 32336.00},
    "C": {"cp1": 31294.60, "cp2": 22530.80, "cp3": 32520.00},
}


@pytest.mark.parametrize("version", ["A", "B", "C"])
def test_the_answers_read_as_a_balance_is_stated(generated, version):
    answers = generated.keys[version]["checkpoints"]

    assert {k: v / 100 for k, v in answers.items()} == STATED[version]


@pytest.mark.parametrize("version", ["A", "B", "C"])
def test_a_liability_checkpoint_is_not_a_negative_number(generated, version):
    """The one that was unanswerable: Accounts Payable, a credit balance."""
    assert generated.keys[version]["checkpoints"]["cp3"] > 0


@pytest.mark.parametrize("version", ["A", "B", "C"])
def test_every_answer_is_stated_on_the_accounts_own_side(
        generated, version, normal_side, measured):
    """The general rule, so a checkpoint added later cannot reintroduce this."""
    answers = generated.keys[version]["checkpoints"]
    balances = generated.keys[version]["expected_balances"]["adjusted"]

    for key, value in answers.items():
        account = measured[key]
        signed = balances.get(account, 0)
        expected = signed if normal_side[account] == "debit" else -signed
        assert value == expected, f"{key} ({account}) is not stated on its normal side"


def test_the_sign_is_not_simply_dropped(generated, src):
    """Taking the absolute value would pass the tests above and quietly accept a balance on the
    wrong side of its account, which is a real error a student can make and should not pass."""
    from originalentry.generator.build import _checkpoint_value

    debit_account = {"number": "101", "normal_balance": "debit"}
    credit_account = {"number": "201", "normal_balance": "credit"}

    # An overdrawn bank account, and a supplier who owes us: both abnormal, both negative.
    assert _checkpoint_value(-5000, debit_account["normal_balance"]) == -5000
    assert _checkpoint_value(5000, credit_account["normal_balance"]) == -5000
