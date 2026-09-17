"""Detecting the designed errors (T8.5).

Detection starts from the student's entry for one document, because a company's balances are
touched by too many transactions to diagnose from a difference alone. Only an error with no
single document behind it falls back to the balances, and it is reported as a possibility.

This is diagnosis for the instructor, never an accusation and never a word to the student.
"""

from dataclasses import replace

import pytest
from parchment.grading import grade
from parchment.packs import replay, schema

from tests.packs import testco_alpha
from tests.work import perfect_work


@pytest.fixture(scope="module")
def pack():
    return schema.load_pack(testco_alpha.PACK)


@pytest.fixture(scope="module")
def key():
    return schema.load_answer_key(testco_alpha.KEY_A)


def _entry_id(snapshot, document_ref):
    for entry_id, entry in snapshot.entries.items():
        if entry.document_ref == document_ref:
            return entry_id
    raise AssertionError(f"no entry for {document_ref}")


def test_work_that_follows_the_key_raises_no_signature(pack, key):
    result = grade(perfect_work(pack, key), pack, key)

    assert result.signatures == ()
    assert result.unexplained == ()


def test_a_sale_in_an_expense_account_is_named_from_the_entry(pack, key):
    snapshot = replay.build_replay_snapshot(pack, key)
    entry_id = _entry_id(snapshot, "INV-2")
    entry = snapshot.entries[entry_id]
    snapshot.entries[entry_id] = replace(entry, lines=tuple(
        replace(line, account_number="611", debit_cents=line.credit_cents, credit_cents=0)
        if line.account_number == "401" else line
        for line in entry.lines
    ))

    result = grade(perfect_work(pack, key, snapshot=snapshot), pack, key)

    named = [s.label for s in result.signatures]
    assert "Recorded a sale in an expense account" in named
    assert all(s.confident for s in result.signatures)


def test_an_invoice_recorded_above_its_face_is_named_by_its_figure(pack, key):
    snapshot = replay.build_replay_snapshot(pack, key)
    entry_id = _entry_id(snapshot, "INV-1")
    entry = snapshot.entries[entry_id]
    snapshot.entries[entry_id] = replace(entry, lines=tuple(
        replace(line, debit_cents=130000 if line.debit_cents else 0,
                credit_cents=130000 if line.credit_cents else 0)
        for line in entry.lines
    ))

    result = grade(perfect_work(pack, key, snapshot=snapshot), pack, key)

    assert "Recorded the invoice above its face" in [s.label for s in result.signatures]


def test_an_error_with_no_document_behind_it_is_reported_as_a_possibility(pack, key):
    snapshot = replay.build_replay_snapshot(pack, key)
    for entry_id, entry in list(snapshot.entries.items()):
        if entry.kind == "adjusting":  # the depreciation adjustment was never recorded
            del snapshot.entries[entry_id]
    snapshot.general_postings = tuple(
        replace(p, entry_ids=tuple(i for i in p.entry_ids if i in snapshot.entries))
        for p in snapshot.general_postings
    )

    result = grade(perfect_work(pack, key, snapshot=snapshot), pack, key)

    depreciation = [s for s in result.signatures if s.key == "depreciation_missed"]
    assert depreciation, [s.key for s in result.signatures]
    assert not depreciation[0].confident  # a possibility, drawn from the balances


def test_a_difference_no_signature_explains_is_listed_for_the_instructor(pack, key):
    snapshot = replay.build_replay_snapshot(pack, key)
    entry_id = _entry_id(snapshot, "INV-1")
    entry = snapshot.entries[entry_id]
    snapshot.entries[entry_id] = replace(entry, lines=tuple(
        replace(line, debit_cents=111100 if line.debit_cents else 0,
                credit_cents=111100 if line.credit_cents else 0)
        for line in entry.lines
    ))

    result = grade(perfect_work(pack, key, snapshot=snapshot), pack, key)

    assert result.unexplained
    assert any(number == "112" for number, _ in result.unexplained)
