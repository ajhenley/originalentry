"""Submitting an attempt at a chapter problem.

Two promises are load-bearing here and neither is visible in the happy path. A submission refused
for being out of balance must cost nothing -- not the attempt count, not the disclosure level, not
the entry the student already had -- because an attempt lost to a typo is a defect. And submitting
must *replace*, so a problem never has two entries that still stand: the grader asks for review
when one does, and without replacement every problem a student tried twice would ask for it.
"""

from __future__ import annotations

import pytest
from originalentry.extensions import db
from originalentry.models import (
    Account,
    Assignment,
    ProblemAttempt,
    Section,
    User,
    Variant,
    Workspace,
)
from originalentry.problems import importing
from originalentry.services.problems import (
    LEVEL_ANSWER,
    LEVEL_LINES,
    LEVEL_SHAPE,
    attempt_for,
    attempts_for,
    entries_for,
    feedback_level,
    live_entry,
    reveal,
    submit,
)
from sqlalchemy import select

from tests.unit.test_chapter_file import VALID

pytestmark = pytest.mark.db

#: P3-01's entry, as the key has it: equipment bought part in cash, part on account.
RIGHT = {
    "entry_date": "2026-10-05",
    "line-1-account": "150", "line-1-debit": "4800.00", "line-1-credit": "",
    "line-2-account": "101", "line-2-debit": "", "line-2-credit": "1800.00",
    "line-3-account": "201", "line-3-debit": "", "line-3-credit": "3000.00",
}

#: The same entry with the cash figure mistyped, so debits and credits disagree.
TYPO = {**RIGHT, "line-2-credit": "180.00"}

#: Balanced, but the wrong account for the thing bought.
WRONG_ACCOUNT = {**RIGHT, "line-1-account": "140"}


@pytest.fixture
def workspace(session):
    version = importing.import_chapter(session, VALID)
    student = User(email="pat@example.edu", given_name="Ada", family_name="Sowande")
    section = Section(name="Sec", join_code="pat-join")
    session.add_all([student, section])
    session.flush()
    assignment = Assignment(section_id=section.id, title="Chapter 3", company_policy="fixed",
                            fixed_pack_version_id=version.id, problems_required=2)
    session.add(assignment)
    session.flush()
    variant_id = session.scalars(
        select(Variant.id).where(Variant.pack_version_id == version.id)).one()
    ws = Workspace(assignment_id=assignment.id, student_id=student.id,
                   pack_version_id=version.id, variant_id=variant_id, status="in_progress")
    session.add(ws)
    session.flush()
    return ws


def _entries(session, ws, ref):
    return entries_for(session, ws, ref)


# ── a refusal costs nothing ────────────────────────────────────────────────────────────

def test_an_out_of_balance_submission_is_refused(session, workspace):
    result = submit(session, workspace, "P3-01", TYPO)

    assert result.accepted is False
    assert any("balance" in message.lower() for _field, message in result.errors)


def test_an_out_of_balance_submission_does_not_consume_an_attempt(session, workspace):
    """Review Focus 1, and the anti-goal: a typo must not advance the disclosure."""
    submit(session, workspace, "P3-01", TYPO)
    submit(session, workspace, "P3-01", TYPO)

    attempt = attempt_for(session, workspace, "P3-01")

    assert attempt is None or attempt.attempts == 0
    assert feedback_level(attempt) == LEVEL_SHAPE


def test_an_out_of_balance_submission_records_no_entry(session, workspace):
    submit(session, workspace, "P3-01", TYPO)

    assert _entries(session, workspace, "P3-01") == []


def test_a_refusal_does_not_disturb_the_entry_already_there(session, workspace):
    """The cruellest version of the bug: a student with a correct entry mistypes a correction and
    loses the work that was standing."""
    submit(session, workspace, "P3-01", RIGHT)
    before = live_entry(session, workspace, "P3-01")

    submit(session, workspace, "P3-01", TYPO)

    after = live_entry(session, workspace, "P3-01")
    assert after is not None
    assert after.id == before.id
    assert attempt_for(session, workspace, "P3-01").attempts == 1


def test_a_single_line_entry_is_refused_without_consuming_an_attempt(session, workspace):
    one_line = {"entry_date": "2026-10-05",
                "line-1-account": "150", "line-1-debit": "4800.00", "line-1-credit": ""}

    result = submit(session, workspace, "P3-01", one_line)

    assert result.accepted is False
    assert attempt_for(session, workspace, "P3-01") is None


# ── submitting replaces ────────────────────────────────────────────────────────────────

def test_submitting_replaces_the_previous_entry(session, workspace):
    """Otherwise entries_for_document returns two and every problem asks for review."""
    submit(session, workspace, "P3-01", WRONG_ACCOUNT)
    submit(session, workspace, "P3-01", WRONG_ACCOUNT)
    submit(session, workspace, "P3-01", RIGHT)

    everything = _entries(session, workspace, "P3-01")
    live = [entry for entry in everything if entry.voided_at is None]

    assert len(live) == 1, "a problem has more than one entry that still stands"
    assert len(everything) == 3, "the replaced entries were deleted rather than voided"


def test_the_replaced_entries_say_why_they_were_voided(session, workspace):
    """A staff member reading the entry history should not have to guess."""
    submit(session, workspace, "P3-01", WRONG_ACCOUNT)
    submit(session, workspace, "P3-01", RIGHT)

    voided = [e for e in _entries(session, workspace, "P3-01") if e.voided_at is not None]

    assert len(voided) == 1
    assert "attempt" in (voided[0].void_reason or "").lower()


def test_the_live_entry_is_the_latest_one(session, workspace):
    """EntryLine carries account_id, not a number -- the composite scope again -- so the accounts
    are read back through the chart."""
    submit(session, workspace, "P3-01", WRONG_ACCOUNT)
    submit(session, workspace, "P3-01", RIGHT)

    entry = live_entry(session, workspace, "P3-01")
    numbers = {
        session.get(Account, line.account_id).number for line in entry.lines
    }

    assert "150" in numbers, "the correcting entry is not the one standing"
    assert "140" not in numbers, "the replaced entry's account is still standing"


def test_each_problem_keeps_its_own_entry(session, workspace):
    """Replacement is per problem. Replacing across problems would wipe a student's chapter."""
    submit(session, workspace, "P3-01", RIGHT)
    submit(session, workspace, "P3-02", {
        "entry_date": "2026-10-08",
        "line-1-account": "201", "line-1-debit": "1200.00", "line-1-credit": "",
        "line-2-account": "101", "line-2-debit": "", "line-2-credit": "1200.00"})

    assert live_entry(session, workspace, "P3-01") is not None
    assert live_entry(session, workspace, "P3-02") is not None


# ── the count, and what it unlocks ─────────────────────────────────────────────────────

def test_an_accepted_submission_counts(session, workspace):
    submit(session, workspace, "P3-01", WRONG_ACCOUNT)

    assert attempt_for(session, workspace, "P3-01").attempts == 1
    assert feedback_level(attempt_for(session, workspace, "P3-01")) == LEVEL_SHAPE


def test_the_second_attempt_unlocks_the_lines(session, workspace):
    submit(session, workspace, "P3-01", WRONG_ACCOUNT)
    submit(session, workspace, "P3-01", WRONG_ACCOUNT)

    assert feedback_level(attempt_for(session, workspace, "P3-01")) == LEVEL_LINES


def test_the_attempt_count_survives_a_reload(session, workspace):
    """Server-side state, read back from the database rather than from anything a page carried."""
    submit(session, workspace, "P3-01", WRONG_ACCOUNT)
    submit(session, workspace, "P3-01", WRONG_ACCOUNT)
    session.flush()
    session.expire_all()

    row = session.scalars(db.select(ProblemAttempt).filter_by(
        workspace_id=workspace.id, document_ref="P3-01")).one()

    assert row.attempts == 2


def test_attempts_are_counted_per_problem(session, workspace):
    submit(session, workspace, "P3-01", WRONG_ACCOUNT)
    submit(session, workspace, "P3-01", WRONG_ACCOUNT)
    submit(session, workspace, "P3-02", {
        "entry_date": "2026-10-08",
        "line-1-account": "201", "line-1-debit": "1200.00", "line-1-credit": "",
        "line-2-account": "101", "line-2-debit": "", "line-2-credit": "1200.00"})

    rows = attempts_for(session, workspace)

    assert rows["P3-01"].attempts == 2
    assert rows["P3-02"].attempts == 1


def test_attempts_are_unlimited(session, workspace):
    """Nothing refuses a twelfth try, and the level does not climb past the lines."""
    for _ in range(12):
        submit(session, workspace, "P3-01", WRONG_ACCOUNT)

    attempt = attempt_for(session, workspace, "P3-01")
    assert attempt.attempts == 12
    assert feedback_level(attempt) == LEVEL_LINES


# ── revealing ──────────────────────────────────────────────────────────────────────────

def test_revealing_records_it_and_reaches_the_answer(session, workspace):
    attempt = reveal(session, workspace, "P3-01")

    assert attempt.answer_shown_at is not None
    assert feedback_level(attempt) == LEVEL_ANSWER


def test_revealing_twice_keeps_the_first_time(session, workspace):
    first = reveal(session, workspace, "P3-01").answer_shown_at

    assert reveal(session, workspace, "P3-01").answer_shown_at == first


def test_a_later_submission_does_not_undo_a_reveal(session, workspace):
    """A revealed problem stays practisable and does not come back to life for the mark."""
    reveal(session, workspace, "P3-01")

    submit(session, workspace, "P3-01", RIGHT)

    attempt = attempt_for(session, workspace, "P3-01")
    assert attempt.answer_shown_at is not None
    assert feedback_level(attempt) == LEVEL_ANSWER


def test_revealing_a_problem_never_attempted_works(session, workspace):
    """There is no attempt row yet, and a student who cannot see how to start is exactly who the
    button is for."""
    attempt = reveal(session, workspace, "P3-02")

    assert attempt.attempts == 0
    assert attempt.answer_shown_at is not None


def test_revealing_one_problem_does_not_reveal_another(session, workspace):
    reveal(session, workspace, "P3-01")

    assert attempt_for(session, workspace, "P3-02") is None


def test_one_student_s_attempts_do_not_reach_another_s(session, workspace):
    other_student = User(email="pat2@example.edu", given_name="Bo", family_name="Adeyemi")
    session.add(other_student)
    session.flush()
    other = Workspace(assignment_id=workspace.assignment_id, student_id=other_student.id,
                      pack_version_id=workspace.pack_version_id,
                      variant_id=workspace.variant_id, status="in_progress")
    session.add(other)
    session.flush()

    submit(session, workspace, "P3-01", WRONG_ACCOUNT)
    submit(session, workspace, "P3-01", WRONG_ACCOUNT)

    assert attempt_for(session, other, "P3-01") is None
    assert feedback_level(attempt_for(session, other, "P3-01")) == LEVEL_SHAPE
