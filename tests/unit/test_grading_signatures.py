"""Detecting the designed errors (T8.5).

Detection starts from the student's entry for one document, because a company's balances are
touched by too many transactions to diagnose from a difference alone. Only an error with no
single document behind it falls back to the balances, and it is reported as a possibility.

This is diagnosis for the instructor, never an accusation and never a word to the student.
"""

from dataclasses import replace

import pytest
from originalentry.grading import grade
from originalentry.packs import replay, schema

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


# ── A deduction the pack asked for (T8.5) ───────────────────────────────────────────────
#
# A signature changes no mark unless the pack sets `deduct_points`. Until now the field was
# carried in the schema and ignored by the engine, so an author could set it, watch the pack
# validate, and never find out that nothing happened.
#
# A deduction applies once, it cannot take a student below zero, and — the judgement the engine
# makes here — only a *confident* signature deducts. The balance-delta fallback says "possibly",
# and this app does not take marks off a maybe; it sends it to a human instead.

def _with_deduction(key, signature_key: str, points: int):
    """The same key, with the pack asking for a deduction on one signature."""
    return key.model_copy(update={"error_signatures": [
        s.model_copy(update={"deduct_points": points}) if s.key == signature_key else s
        for s in key.error_signatures
    ]})


def _sale_in_an_expense_account(pack, key):
    snapshot = replay.build_replay_snapshot(pack, key)
    entry_id = _entry_id(snapshot, "INV-2")
    entry = snapshot.entries[entry_id]
    snapshot.entries[entry_id] = replace(entry, lines=tuple(
        replace(line, account_number="611", debit_cents=line.credit_cents, credit_cents=0)
        if line.account_number == "401" else line
        for line in entry.lines
    ))
    return perfect_work(pack, key, snapshot=snapshot)


def test_without_deduct_points_a_signature_changes_no_mark(pack, key):
    work = _sale_in_an_expense_account(pack, key)

    result = grade(work, pack, key)

    assert result.signatures
    assert result.deductions == ()
    assert result.total_points == sum(c.points for c in result.components)


def test_a_pack_that_asks_for_a_deduction_gets_one(pack, key):
    work = _sale_in_an_expense_account(pack, key)
    before = grade(work, pack, key).total_points

    result = grade(work, pack, _with_deduction(key, "sale_to_an_expense_account", 2))

    assert [d.points for d in result.deductions] == [2.0]
    assert result.total_points == before - 2


def test_the_deduction_is_named_so_an_instructor_can_see_why(pack, key):
    work = _sale_in_an_expense_account(pack, key)

    result = grade(work, pack, _with_deduction(key, "sale_to_an_expense_account", 2))

    assert result.deductions[0].label == "Recorded a sale in an expense account"


def test_it_applies_once(pack, key):
    """Twice for one error would be marking the same slip two ways."""
    work = _sale_in_an_expense_account(pack, key)

    result = grade(work, pack, _with_deduction(key, "sale_to_an_expense_account", 2))

    assert len(result.deductions) == 1


def test_a_deduction_cannot_take_a_student_below_zero(pack, key):
    work = _sale_in_an_expense_account(pack, key)

    result = grade(work, pack, _with_deduction(key, "sale_to_an_expense_account", 10_000))

    assert result.total_points == 0


def test_a_possibility_never_costs_a_student_marks(pack, key):
    """The fallback says "possibly". This app does not take marks off a maybe."""
    snapshot = replay.build_replay_snapshot(pack, key)
    for entry_id, entry in list(snapshot.entries.items()):
        if entry.kind == "adjusting":
            del snapshot.entries[entry_id]
    snapshot.general_postings = tuple(
        replace(p, entry_ids=tuple(i for i in p.entry_ids if i in snapshot.entries))
        for p in snapshot.general_postings
    )
    work = perfect_work(pack, key, snapshot=snapshot)
    asked = _with_deduction(key, "depreciation_missed", 3)

    result = grade(work, pack, asked)

    assert any(s.key == "depreciation_missed" for s in result.signatures)
    assert result.deductions == ()


def test_a_possibility_the_pack_would_deduct_for_goes_to_a_human(pack, key):
    """Refusing to deduct silently would hide it; the grader is told to decide."""
    snapshot = replay.build_replay_snapshot(pack, key)
    for entry_id, entry in list(snapshot.entries.items()):
        if entry.kind == "adjusting":
            del snapshot.entries[entry_id]
    snapshot.general_postings = tuple(
        replace(p, entry_ids=tuple(i for i in p.entry_ids if i in snapshot.entries))
        for p in snapshot.general_postings
    )
    work = perfect_work(pack, key, snapshot=snapshot)

    result = grade(work, pack, _with_deduction(key, "depreciation_missed", 3))

    assert result.needs_review
