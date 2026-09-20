"""Integer-cent money parsing and formatting (T7.1, D6 rule 1).

Money is integer cents *everywhere*. There is never a float. Parsing goes through ``Decimal``
to an ``int`` of cents; formatting works from integer cents.

This module is pure stdlib so the ledger engine may depend on it. It raises :class:`MoneyError`
with a stable ``reason`` code; the student-facing wording for each reason lives in
``originalentry.messages`` (so this module stays free of presentation concerns).
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

# $99,999,999.99 — the largest amount a single entry line may carry.
MAX_CENTS = 9_999_999_999

# Reason codes. Each maps to a student-facing string in messages.MONEY_ERRORS.
EMPTY = "empty"
NOT_A_NUMBER = "not_a_number"
TOO_MANY_DECIMALS = "too_many_decimals"
MISPLACED_COMMA = "misplaced_comma"
NEGATIVE = "negative"
ZERO = "zero"
TOO_LARGE = "too_large"

_GROUPED_INT = re.compile(r"^\d{1,3}(,\d{3})*$")
_PLAIN_INT = re.compile(r"^\d+$")
_FRAC = re.compile(r"^\d+$")


class MoneyError(ValueError):
    """A rejected money input. ``reason`` is one of the module-level codes."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def parse_money(raw: str | None) -> int:
    """Parse a user-entered amount into a positive integer number of cents.

    Accepts ``1234.5``, ``1,234.50`` and ``$1,234.50``. Rejects more than two decimal
    places, misplaced thousands commas, a leading ``-`` or ``(``, zero, and amounts over
    $99,999,999.99. Raises :class:`MoneyError` on any rejected input.
    """
    if raw is None:
        raise MoneyError(EMPTY)
    s = raw.strip()
    if not s:
        raise MoneyError(EMPTY)

    # Signals of a negative amount are refused outright rather than coerced.
    if s[0] in "-(" or ")" in s:
        raise MoneyError(NEGATIVE)

    if s.startswith("$"):
        s = s[1:].strip()
    if not s:
        raise MoneyError(EMPTY)
    if "-" in s or "(" in s:
        raise MoneyError(NEGATIVE)

    if s.count(".") > 1:
        raise MoneyError(NOT_A_NUMBER)

    if "." in s:
        int_part, frac_part = s.split(".")
        if not _FRAC.match(frac_part):
            raise MoneyError(NOT_A_NUMBER)
        if len(frac_part) > 2:
            raise MoneyError(TOO_MANY_DECIMALS)
    else:
        int_part, frac_part = s, ""

    if int_part == "":
        raise MoneyError(NOT_A_NUMBER)

    if "," in int_part:
        if not _GROUPED_INT.match(int_part):
            raise MoneyError(MISPLACED_COMMA)
        digits = int_part.replace(",", "")
    else:
        if not _PLAIN_INT.match(int_part):
            raise MoneyError(NOT_A_NUMBER)
        digits = int_part

    frac2 = (frac_part + "00")[:2]
    try:
        # Two decimal places at most, so scaling by 100 is exact.
        cents = int((Decimal(f"{digits}.{frac2}") * 100).to_integral_value())
    except InvalidOperation:
        raise MoneyError(NOT_A_NUMBER) from None

    if cents == 0:
        raise MoneyError(ZERO)
    if cents > MAX_CENTS:
        raise MoneyError(TOO_LARGE)
    return cents


def format_cents(cents: int) -> str:
    """Format integer cents as a grouped decimal string, e.g. ``1,234.50``.

    Handles negatives for display (a leading ``-``); the ledger is debit-positive and the
    display layer decides sign, so formatting must accept either.
    """
    sign = "-" if cents < 0 else ""
    whole, rem = divmod(abs(cents), 100)
    return f"{sign}{whole:,}.{rem:02d}"


def format_dollars(cents: int) -> str:
    """Format integer cents with a currency symbol, e.g. ``$1,234.50`` or ``-$5.00``."""
    sign = "-" if cents < 0 else ""
    return f"{sign}${format_cents(abs(cents))}"
