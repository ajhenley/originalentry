"""Money parser and formatter (T7.1). Round-trips and rejections (T17.3 Money guard)."""

import pytest
from parchment import money


@pytest.mark.parametrize(
    ("raw", "cents"),
    [
        ("1234.5", 123450),
        ("1,234.50", 123450),
        ("$1,234.50", 123450),
        ("1680.00", 168000),
        ("0.01", 1),
        ("5", 500),
        ("1,234", 123400),
        ("  42  ", 4200),
        ("$0.99", 99),
        ("99,999,999.99", money.MAX_CENTS),
    ],
)
def test_parse_accepts(raw, cents):
    assert money.parse_money(raw) == cents


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ("1.234", money.TOO_MANY_DECIMALS),
        ("-5", money.NEGATIVE),
        ("(5)", money.NEGATIVE),
        ("1,23", money.MISPLACED_COMMA),
        ("12,34", money.MISPLACED_COMMA),
        ("1,2345", money.MISPLACED_COMMA),
        ("$", money.EMPTY),
        ("", money.EMPTY),
        ("   ", money.EMPTY),
        (None, money.EMPTY),
        ("0", money.ZERO),
        ("0.00", money.ZERO),
        ("abc", money.NOT_A_NUMBER),
        ("1.2.3", money.NOT_A_NUMBER),
        ("100000000.00", money.TOO_LARGE),
    ],
)
def test_parse_rejects(raw, reason):
    with pytest.raises(money.MoneyError) as exc:
        money.parse_money(raw)
    assert exc.value.reason == reason


def test_round_trip():
    for cents in (1, 99, 100, 123450, money.MAX_CENTS):
        assert money.parse_money(money.format_cents(cents)) == cents


def test_format():
    assert money.format_cents(123450) == "1,234.50"
    assert money.format_cents(5) == "0.05"
    assert money.format_cents(-14000) == "-140.00"
    assert money.format_dollars(14000) == "$140.00"
    assert money.format_dollars(-14000) == "-$140.00"
