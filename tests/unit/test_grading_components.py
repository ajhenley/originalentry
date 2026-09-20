"""Grading components, on the student's own figures (T8.2).

The engine is pure: it takes the student's work, the pack and the key, and returns points with
the evidence behind them. These tests build work from the answer-key replay (a student who did
everything as the key does) and then introduce one mistake at a time, to show that the mistake
costs marks **once** and that every other component carries on unaffected.
"""

from dataclasses import replace

import pytest
from originalentry.grading import grade
from originalentry.ledger.models import GENERAL, Posting
from originalentry.packs import replay, schema

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


def _entry_id(snapshot, document_ref):
    for entry_id, entry in snapshot.entries.items():
        if entry.document_ref == document_ref:
            return entry_id
    raise AssertionError(f"no entry for {document_ref}")


def _replace_entry(snapshot, document_ref, **changes):
    entry_id = _entry_id(snapshot, document_ref)
    snapshot.entries[entry_id] = replace(snapshot.entries[entry_id], **changes)
    return entry_id


def _points(result, key):
    return result.component(key).points


# ── the whole cycle, done as the key does it ────────────────────────────────────────────

def test_work_that_follows_the_key_earns_every_implemented_component(pack, key):
    result = grade(_work(pack, key), pack, key)

    for component in result.components:
        assert component.points == pytest.approx(component.max_points), component.key
    assert not result.needs_review


# ── triage ──────────────────────────────────────────────────────────────────────────────

def test_triage_is_marked_one_document_at_a_time(pack, key):
    work = _work(pack, key, dispositions={"INV-1": "record", "INV-2": "no_entry"})

    triage = grade(work, pack, key).component("triage")

    assert triage.points == pytest.approx(triage.max_points / 2)
    assert any("INV-2" in row.item for row in triage.evidence)


def test_a_document_never_handled_earns_nothing_for_triage(pack, key):
    work = _work(pack, key, dispositions={"INV-1": "record"})

    triage = grade(work, pack, key).component("triage")

    assert triage.points == pytest.approx(triage.max_points / 2)


# ── journal selection is independent of the amounts (the method-not-match heart) ────────

def test_a_document_in_the_wrong_journal_costs_only_journal_selection(pack, key):
    snapshot = replay.build_replay_snapshot(pack, key)
    entry_id = _replace_entry(snapshot, "INV-2", journal_key="general")
    snapshot.general_postings = tuple(
        replace(p, entry_ids=tuple(i for i in p.entry_ids if i != entry_id))
        for p in snapshot.general_postings
    ) + (Posting(journal_key="general", target=GENERAL, ordinal=1, entry_ids=(entry_id,)),)

    result = grade(_work(pack, key, snapshot=snapshot), pack, key)

    selection = result.component("journal_selection")
    assert selection.points == pytest.approx(selection.max_points / 2)
    # Everything downstream is judged on the student's own figures, so nothing else moves.
    assert _points(result, "entry_accuracy") == pytest.approx(
        result.component("entry_accuracy").max_points
    )
    assert _points(result, "posting_completeness") == pytest.approx(
        result.component("posting_completeness").max_points
    )


# ── entry accuracy: structure and amounts, per document ─────────────────────────────────

def test_the_wrong_account_costs_part_of_one_document(pack, key):
    snapshot = replay.build_replay_snapshot(pack, key)
    entry = snapshot.entries[_entry_id(snapshot, "INV-2")]
    lines = tuple(
        replace(line, account_number="611") if line.account_number == "401" else line
        for line in entry.lines
    )
    _replace_entry(snapshot, "INV-2", lines=lines)

    accuracy = grade(_work(pack, key, snapshot=snapshot), pack, key).component("entry_accuracy")

    per_document = accuracy.max_points / 2
    assert 0 < accuracy.points < accuracy.max_points
    assert accuracy.points > per_document  # the other document is untouched


def test_the_right_accounts_with_the_wrong_figure_keep_the_structure_marks(pack, key):
    snapshot = replay.build_replay_snapshot(pack, key)
    entry = snapshot.entries[_entry_id(snapshot, "INV-2")]
    lines = tuple(
        replace(line, debit_cents=line.debit_cents + 1000 if line.debit_cents else 0,
                credit_cents=line.credit_cents + 1000 if line.credit_cents else 0)
        for line in entry.lines
    )
    _replace_entry(snapshot, "INV-2", lines=lines)

    accuracy = grade(_work(pack, key, snapshot=snapshot), pack, key).component("entry_accuracy")

    per_document = accuracy.max_points / 2
    assert accuracy.points == pytest.approx(per_document + per_document / 2)


def test_a_document_with_two_live_entries_is_sent_for_review(pack, key):
    snapshot = replay.build_replay_snapshot(pack, key)
    entry = snapshot.entries[_entry_id(snapshot, "INV-1")]
    snapshot.entries[99] = replace(entry, id=99)

    result = grade(_work(pack, key, snapshot=snapshot), pack, key)

    assert result.needs_review
    assert any("INV-1" in reason for reason in result.component("entry_accuracy").review_reasons)


# ── posting and the subsidiary proof, on the student's own books ────────────────────────

def test_work_left_unposted_costs_posting_completeness(pack, key):
    """Both ledgers count: the general ledger for every entry, the subsidiary for party lines."""
    snapshot = replay.build_replay_snapshot(pack, key)
    snapshot.general_postings = ()  # posted to the customers' ledger only

    posting = grade(_work(pack, key, snapshot=snapshot), pack, key).component(
        "posting_completeness"
    )
    # The customers' ledger postings still stand, so some credit survives.
    assert 0 < posting.points < posting.max_points

    snapshot.subsidiary_postings = ()  # nothing posted at all
    nothing_posted = grade(_work(pack, key, snapshot=snapshot), pack, key).component(
        "posting_completeness"
    )
    assert nothing_posted.points == 0
    assert "outstanding" in nothing_posted.evidence[0].detail


def test_subsidiary_agreement_compares_the_students_own_totals(pack, key):
    snapshot = replay.build_replay_snapshot(pack, key)
    snapshot.subsidiary_postings = ()  # the customers' ledger was never posted

    agreement = grade(_work(pack, key, snapshot=snapshot), pack, key).component(
        "subsidiary_agreement"
    )

    assert agreement.points == 0
    assert any("customer" in row.item for row in agreement.evidence)
