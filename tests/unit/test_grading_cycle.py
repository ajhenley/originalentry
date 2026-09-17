"""Grading the end of the cycle: adjustments and closing (T8.2, tension 8).

An adjustment's *form* — which accounts, which side — is marked for every adjustment. Its
**amount** is marked only where the key says the figure can be worked out from the documents and
policies alone (``independent``). An amount that depends on a balance an earlier slip could have
changed is left to the grader, with the student's own base figure beside it.

Closing is judged on the student's own books: are the temporary accounts cleared, is income
summary empty, and did retained earnings move by their own net income less their own drawings.
"""

from dataclasses import replace

import pytest
from parchment.grading import grade
from parchment.ledger.models import ADJUSTING, CLOSING
from parchment.packs import replay, schema

from tests.packs import testco_alpha
from tests.work import perfect_work


@pytest.fixture(scope="module")
def pack():
    return schema.load_pack(testco_alpha.PACK)


@pytest.fixture(scope="module")
def key():
    return schema.load_answer_key(testco_alpha.KEY_A)


def _work(pack, key, **changes):
    """A student who did everything the way the key does, unless a test says otherwise."""
    return perfect_work(pack, key, **changes)


def _entry_of_kind(snapshot, kind):
    for entry_id, entry in snapshot.entries.items():
        if entry.kind == kind:
            return entry_id, entry
    raise AssertionError(f"no {kind} entry in the replay")


# ── adjustment form ─────────────────────────────────────────────────────────────────────

def test_the_replay_earns_the_adjustment_components(pack, key):
    result = grade(_work(pack, key), pack, key)

    for component_key in ("adjustment_form", "adjustment_amounts", "closing"):
        component = result.component(component_key)
        assert component.points == pytest.approx(component.max_points), component_key


def test_an_adjustment_on_the_wrong_side_loses_its_form_marks(pack, key):
    snapshot = replay.build_replay_snapshot(pack, key)
    entry_id, entry = _entry_of_kind(snapshot, ADJUSTING)
    flipped = tuple(
        replace(line, debit_cents=line.credit_cents, credit_cents=line.debit_cents)
        for line in entry.lines
    )
    snapshot.entries[entry_id] = replace(entry, lines=flipped)

    result = grade(_work(pack, key, snapshot=snapshot), pack, key)

    assert result.component("adjustment_form").points == 0
    assert result.component("adjustment_form").needs_review  # an entry that matches no pattern


def test_an_independent_amount_is_marked_against_the_key(pack, key):
    snapshot = replay.build_replay_snapshot(pack, key)
    entry_id, entry = _entry_of_kind(snapshot, ADJUSTING)
    bumped = tuple(
        replace(line,
                debit_cents=line.debit_cents + 500 if line.debit_cents else 0,
                credit_cents=line.credit_cents + 500 if line.credit_cents else 0)
        for line in entry.lines
    )
    snapshot.entries[entry_id] = replace(entry, lines=bumped)

    result = grade(_work(pack, key, snapshot=snapshot), pack, key)

    assert result.component("adjustment_form").points == pytest.approx(
        result.component("adjustment_form").max_points
    )  # the form is untouched: the right accounts, the right sides
    assert result.component("adjustment_amounts").points == 0


# ── closing, on the student's own figures ───────────────────────────────────────────────

def test_a_temporary_account_left_open_costs_closing_marks(pack, key):
    snapshot = replay.build_replay_snapshot(pack, key)
    entry_id, entry = _entry_of_kind(snapshot, CLOSING)
    # Drop one closing entry: something that should have been cleared still has a balance.
    del snapshot.entries[entry_id]
    snapshot.general_postings = tuple(
        replace(p, entry_ids=tuple(i for i in p.entry_ids if i != entry_id))
        for p in snapshot.general_postings
    )

    closing = grade(_work(pack, key, snapshot=snapshot), pack, key).component("closing")

    assert 0 <= closing.points < closing.max_points
    assert any(row.earned < row.possible for row in closing.evidence)


def test_books_that_were_never_closed_earn_nothing_and_say_why(pack, key):
    snapshot = replay.build_replay_snapshot(pack, key)
    for entry_id, entry in list(snapshot.entries.items()):
        if entry.kind == CLOSING:
            del snapshot.entries[entry_id]
    snapshot.general_postings = tuple(
        replace(p, entry_ids=tuple(i for i in p.entry_ids if i in snapshot.entries))
        for p in snapshot.general_postings
    )

    closing = grade(_work(pack, key, snapshot=snapshot), pack, key).component("closing")

    # An account that never held anything is not an account that was closed, so the engine says
    # what is true — no closing entries were recorded — rather than handing out marks for it.
    assert closing.points == 0
    assert "No closing entries" in closing.evidence[0].detail
