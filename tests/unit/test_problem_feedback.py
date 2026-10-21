"""How much a student is told, and when.

The progressive design is the whole point of the feature: attempt one says what *kind* of thing is
wrong and withholds which line, so a student has to look. Attempt two and every later one shows
the per-line marks and the signature's sentence. Only an explicit button reaches the answer.

Pure: these two functions decide what to show from an attempt row and a comparison, with no
session and no request.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from originalentry.models import ProblemAttempt
from originalentry.services.problems import (
    LEVEL_ANSWER,
    LEVEL_LINES,
    LEVEL_SHAPE,
    SHAPE_ACCOUNT,
    SHAPE_AMOUNT,
    SHAPE_BALANCE,
    SHAPE_DIRECTION,
    SHAPE_MATCHED,
    feedback_level,
    matches,
    shape_of_error,
)

#: (account, party, side) -> cents, the shape `grading.components.documents` merges lines into.
EXPECTED = {("150", None, "debit"): 480000,
            ("101", None, "credit"): 180000,
            ("201", None, "credit"): 300000}


def _attempt(attempts: int = 0, revealed: bool = False) -> ProblemAttempt:
    return ProblemAttempt(
        workspace_id=1, document_ref="P3-01", attempts=attempts,
        answer_shown_at=datetime.now(UTC) if revealed else None,
    )


# ── when each level is reached ─────────────────────────────────────────────────────────

def test_a_problem_never_touched_gets_shape_only():
    """No row at all: the student has not submitted, so there is nothing to show yet anyway."""
    assert feedback_level(None) == LEVEL_SHAPE


def test_the_first_attempt_gets_shape_only():
    assert feedback_level(_attempt(attempts=1)) == LEVEL_SHAPE


@pytest.mark.parametrize("count", [2, 3, 9, 40])
def test_the_second_attempt_and_every_later_one_gets_the_lines(count):
    """Attempts are unlimited, and only the button goes further -- so level 2 is where a student
    who keeps trying stays."""
    assert feedback_level(_attempt(attempts=count)) == LEVEL_LINES


@pytest.mark.parametrize("count", [0, 1, 2, 50])
def test_only_a_reveal_reaches_the_answer(count):
    """A8 is exempted for problem sets, but only behind the button: the attempt count never
    reaches the answer on its own, however many times a student tries."""
    assert feedback_level(_attempt(attempts=count, revealed=True)) == LEVEL_ANSWER


def test_the_levels_are_ordered_so_a_template_can_compare_them():
    assert LEVEL_SHAPE < LEVEL_LINES < LEVEL_ANSWER


# ── what "shape" says, and what it must not ────────────────────────────────────────────

def test_a_wrong_account_is_named_as_an_account_problem():
    submitted = {("140", None, "debit"): 480000,
                 ("101", None, "credit"): 180000,
                 ("201", None, "credit"): 300000}

    assert shape_of_error(EXPECTED, submitted) == SHAPE_ACCOUNT


def test_a_reversed_entry_is_named_as_a_direction_problem():
    """The accounts are right and the sides are swapped, which is a different misunderstanding
    from picking the wrong account and deserves a different nudge."""
    submitted = {("150", None, "credit"): 480000,
                 ("101", None, "debit"): 180000,
                 ("201", None, "debit"): 300000}

    assert shape_of_error(EXPECTED, submitted) == SHAPE_DIRECTION


def test_a_wrong_figure_is_named_as_an_amount_problem():
    """Balanced, and on the right accounts and sides -- the figures are simply not the key's. An
    entry with one figure changed would be unbalanced and reported as that instead, which is why
    this scales both sides."""
    submitted = {("150", None, "debit"): 470000,
                 ("101", None, "credit"): 170000,
                 ("201", None, "credit"): 300000}

    assert shape_of_error(EXPECTED, submitted) == SHAPE_AMOUNT


def test_an_unbalanced_entry_is_named_as_a_balance_problem():
    """submit() refuses these, so this is the fallback for an entry recorded another way."""
    submitted = {("150", None, "debit"): 480000, ("101", None, "credit"): 180000}

    assert shape_of_error(EXPECTED, submitted) == SHAPE_BALANCE


def test_an_entry_that_matches_has_no_shape():
    assert shape_of_error(EXPECTED, dict(EXPECTED)) == SHAPE_MATCHED


def test_nothing_recorded_is_an_account_problem_not_a_crash():
    assert shape_of_error(EXPECTED, {}) == SHAPE_ACCOUNT


def test_no_shape_ever_names_a_line_or_an_account():
    """The whole of level 1. If the shape leaked "150" or "line 2", attempt one would be attempt
    two and the student would never have to look at their own work."""
    submissions = [
        {("140", None, "debit"): 480000, ("101", None, "credit"): 180000,
         ("201", None, "credit"): 300000},
        {("150", None, "credit"): 480000, ("101", None, "debit"): 180000,
         ("201", None, "debit"): 300000},
        {**EXPECTED, ("150", None, "debit"): 470000},
        {("150", None, "debit"): 470000, ("101", None, "credit"): 170000,
         ("201", None, "credit"): 300000},
        {("150", None, "debit"): 480000, ("101", None, "credit"): 180000},
        {},
    ]

    for submitted in submissions:
        shape = shape_of_error(EXPECTED, submitted)
        for account in ("150", "101", "201", "140"):
            assert account not in shape, f"{shape!r} names account {account}"
        for word in ("line", "row", "first", "second", "third"):
            assert word not in shape.lower(), f"{shape!r} points at a line"


# ── matches ────────────────────────────────────────────────────────────────────────────

def test_an_identical_entry_matches():
    assert matches(EXPECTED, dict(EXPECTED)) is True


def test_a_split_line_still_matches():
    """`_key_amounts` and `_student_amounts` merge by (account, party, side) before this sees
    them, so splitting one line across two is not a mistake (T8.3)."""
    merged = {("150", None, "debit"): 480000, ("101", None, "credit"): 480000}
    split = {("150", None, "debit"): 480000, ("101", None, "credit"): 480000}

    assert matches(merged, split) is True


@pytest.mark.parametrize("submitted", [
    {("140", None, "debit"): 480000, ("101", None, "credit"): 480000},
    {("150", None, "debit"): 480001, ("101", None, "credit"): 480001},
    {},
])
def test_anything_else_does_not_match(submitted):
    assert matches({("150", None, "debit"): 480000,
                    ("101", None, "credit"): 480000}, submitted) is False


def test_matches_and_shape_agree():
    """Two functions, one question: a matched entry must have no shape, and an unmatched one must
    always have one. A disagreement would show a student "nothing is wrong" beside a nudge."""
    submissions = [
        dict(EXPECTED),
        {**EXPECTED, ("150", None, "debit"): 1},
        {("140", None, "debit"): 480000, ("101", None, "credit"): 480000},
        {},
    ]

    for submitted in submissions:
        assert matches(EXPECTED, submitted) == (
            shape_of_error(EXPECTED, submitted) == SHAPE_MATCHED)
