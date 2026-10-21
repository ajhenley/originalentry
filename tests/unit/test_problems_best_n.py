"""The best N of a chapter's problems (the only new scoring rule).

The existing components divide their points across every document in the pack, which is exactly
what a problem set must not do: a student who works twelve problems when six count must never be
marked out of twelve. This component selects instead of dividing -- and it has to select the
*best* unrevealed ones, because the promise the feature rests on is that practising beyond the
minimum can never cost a mark.

No database: the component is pure in the work, the pack and the key, like every other one.
"""

from __future__ import annotations

from datetime import date

import pytest
from originalentry.grading.components.problems import problems_best_n
from originalentry.grading.models import StudentWork
from originalentry.ledger.models import Entry, Line, Snapshot
from originalentry.packs import schema

POINTS = 60.0

# A problem's two lines, in cents. The figure differs per problem so a mixed-up entry is visible.
def _amount(index: int) -> int:
    return 10000 + index * 100


def _ref(index: int) -> str:
    return f"P-{index:02d}"


def _key(count: int) -> schema.AnswerKey:
    """A chapter of `count` independent two-line problems."""
    return schema.load_answer_key({
        "variant": "A",
        "triage": {_ref(i): True for i in range(1, count + 1)},
        "expected_entries": [
            {
                "document": _ref(i),
                "journal": "general",
                "lines": [
                    {"account": "101", "debit": _amount(i)},
                    {"account": "401", "credit": _amount(i)},
                ],
            }
            for i in range(1, count + 1)
        ],
    })


def _entry(entry_id: int, ref: str, index: int, *, how: str) -> Entry:
    """One student entry for a problem.

    ``perfect`` is the key's own entry. ``wrong_figure`` keeps both accounts and sides and gets one
    amount wrong, which `_compare` credits at 0.75 -- a partial score, so "best" has something to
    rank. ``wrong_account`` replaces one account, which scores lower still.
    """
    amount = _amount(index)
    if how == "perfect":
        lines = (Line(1, "101", debit_cents=amount), Line(2, "401", credit_cents=amount))
    elif how == "wrong_figure":
        lines = (Line(1, "101", debit_cents=amount), Line(2, "401", credit_cents=amount + 500))
    elif how == "wrong_account":
        lines = (Line(1, "199", debit_cents=amount), Line(2, "401", credit_cents=amount))
    else:
        raise AssertionError(f"unknown shape {how!r}")
    return Entry(id=entry_id, journal_key="general", entry_date=date(2026, 10, 5),
                 kind="regular", lines=lines, document_ref=ref)


def _work(answers: dict[str, str], *, required: int | None,
          revealed=(), duplicates=()) -> StudentWork:
    """A student who answered the problems in `answers`, each the named way.

    `duplicates` names refs to record a *second* live entry for, which is the state submitting is
    supposed to make impossible.
    """
    entries: dict[int, Entry] = {}
    next_id = 1
    for ref, how in answers.items():
        index = int(ref.split("-")[1])
        entries[next_id] = _entry(next_id, ref, index, how=how)
        next_id += 1
        if ref in duplicates:
            entries[next_id] = _entry(next_id, ref, index, how="wrong_account")
            next_id += 1
    return StudentWork(
        snapshot=Snapshot(entries=entries),
        problems_required=required,
        revealed=frozenset(revealed),
    )


def _earned(result) -> float:
    return result.points


# ── selecting the best N ────────────────────────────────────────────────────────────────

def test_only_the_best_n_count():
    """Twenty problems, six required: the six highest scores, and the rest are ignored entirely --
    not averaged in, not subtracted."""
    answers = {_ref(i): ("perfect" if i <= 6 else "wrong_account") for i in range(1, 21)}

    result = problems_best_n(_work(answers, required=6), None, _key(20), POINTS)

    assert _earned(result) == pytest.approx(POINTS)
    assert result.max_points == POINTS


def test_the_best_n_are_chosen_not_the_first_n():
    """The same twenty problems with the perfect ones *last*. A component that took the first six
    it walked would score this a third of the previous test and the bug would be invisible on a
    chapter a student worked in order."""
    answers = {_ref(i): ("wrong_account" if i <= 14 else "perfect") for i in range(1, 21)}

    result = problems_best_n(_work(answers, required=6), None, _key(20), POINTS)

    assert _earned(result) == pytest.approx(POINTS)


def test_the_denominator_is_n_not_the_number_attempted():
    """One problem answered perfectly out of six required is one sixth, not full marks."""
    result = problems_best_n(_work({_ref(1): "perfect"}, required=6), None, _key(20), POINTS)

    assert _earned(result) == pytest.approx(POINTS / 6)


def test_working_more_than_n_never_costs_a_mark():
    """The promise the feature rests on, stated as a test: six perfect problems score the same
    whether the student stopped there or carried on and botched the next six."""
    six = {_ref(i): "perfect" for i in range(1, 7)}
    and_six_more = {**six, **{_ref(i): "wrong_account" for i in range(7, 13)}}

    stopped = problems_best_n(_work(six, required=6), None, _key(20), POINTS)
    carried_on = problems_best_n(_work(and_six_more, required=6), None, _key(20), POINTS)

    assert _earned(carried_on) == pytest.approx(_earned(stopped))


def test_a_partial_answer_earns_a_partial_share():
    """Guards the tests above: if every shape scored the same, "best" would be untestable."""
    perfect = problems_best_n(_work({_ref(1): "perfect"}, required=1), None, _key(20), POINTS)
    partial = problems_best_n(_work({_ref(1): "wrong_figure"}, required=1), None, _key(20), POINTS)
    worse = problems_best_n(_work({_ref(1): "wrong_account"}, required=1), None, _key(20), POINTS)

    assert 0 < _earned(worse) < _earned(partial) < _earned(perfect)


# ── the reveal ──────────────────────────────────────────────────────────────────────────

def test_a_revealed_problem_scores_nothing_however_good_the_entry():
    """Review Focus 4. The entry may be perfect; the answer was shown."""
    result = problems_best_n(
        _work({_ref(1): "perfect"}, required=1, revealed=[_ref(1)]), None, _key(20), POINTS)

    assert _earned(result) == pytest.approx(0.0)


def test_a_revealed_problem_does_not_take_one_of_the_n_slots():
    """Six required, one revealed, seven answered: the best six of the six unrevealed count, so
    revealing one of many costs nothing -- which is what makes the reveal humane."""
    answers = {_ref(i): "perfect" for i in range(1, 8)}

    result = problems_best_n(
        _work(answers, required=6, revealed=[_ref(3)]), None, _key(20), POINTS)

    assert _earned(result) == pytest.approx(POINTS)


def test_the_evidence_says_why_a_revealed_problem_earned_nothing():
    """A staff member reading the evidence must be able to tell a revealed problem from an
    unanswered one; both are zero, and only one of them is a reason to worry."""
    result = problems_best_n(
        _work({_ref(1): "perfect"}, required=1, revealed=[_ref(1)]), None, _key(20), POINTS)

    row = next(r for r in result.evidence if r.item == _ref(1))
    assert "revealed" in row.detail.lower()


# ── evidence and review ────────────────────────────────────────────────────────────────

def test_an_unanswered_problem_appears_in_the_evidence():
    """Six required and two answered: the evidence has to show the four that were not, or the
    screen reads as though the chapter were four problems long."""
    result = problems_best_n(
        _work({_ref(1): "perfect", _ref(2): "perfect"}, required=6), None, _key(20), POINTS)

    items = [row.item for row in result.evidence]
    assert len(items) == len(set(items)), "a problem appears twice in the evidence"
    assert _ref(7) in items


def test_more_than_one_live_entry_for_a_problem_asks_for_review():
    """Mirrors entry_accuracy: it should not happen, because submitting replaces, and if it does
    the mark is not to be trusted."""
    result = problems_best_n(
        _work({_ref(1): "perfect"}, required=1, duplicates=[_ref(1)]), None, _key(20), POINTS)

    assert result.needs_review
    assert any(_ref(1) in reason for reason in result.review_reasons)


def test_a_missing_count_is_flagged_rather_than_guessed_at():
    """An assignment with no problems_required is a staff mistake Task 6 refuses at creation. If
    one reaches grading anyway, scoring it out of every problem is defensible and scoring it out
    of nothing is not -- but either way a human has to be told, because the alternative is a
    whole section's marks quietly computed against the wrong denominator."""
    answers = {_ref(i): "perfect" for i in range(1, 21)}

    result = problems_best_n(_work(answers, required=None), None, _key(20), POINTS)

    assert _earned(result) == pytest.approx(POINTS)
    assert result.needs_review
    assert any("problems_required" in reason for reason in result.review_reasons)


def test_a_revealed_problem_is_not_counted_in_the_fallback_denominator():
    """The one place excluding a revealed problem changes a mark rather than only the evidence.

    A 0.0 score can never displace a positive one, so ranking a revealed problem last instead of
    dropping it leaves every ordinary mark identical -- which makes this the only test that can
    tell the two apart. When problems_required is missing, the fallback counts the problems that
    *could* count: a student who revealed fifteen of twenty and answered the other five perfectly
    has done everything still available to them, and the missing setting is already flagged for
    review.
    """
    answers = {_ref(i): "perfect" for i in range(1, 6)}
    revealed = [_ref(i) for i in range(6, 21)]

    result = problems_best_n(
        _work(answers, required=None, revealed=revealed), None, _key(20), POINTS)

    assert _earned(result) == pytest.approx(POINTS)


def test_a_chapter_with_no_problems_earns_nothing_and_does_not_divide_by_zero():
    result = problems_best_n(_work({}, required=0), None, _key(0), POINTS)

    assert _earned(result) == pytest.approx(0.0)
