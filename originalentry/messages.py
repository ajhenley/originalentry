"""Every student-facing string (Part I §4, A7).

None of these use "correct", "incorrect", "right" or "wrong", and no colour is asked to carry
that meaning either. The A7 guard test renders every route and every string here and fails on
those words as whole words, any case. Keep new strings the same way.

Dynamic strings are functions so the substituted figures stay inside this module.
"""

from __future__ import annotations

from . import money

# ── Entry validation (the write is refused before it reaches the database) ──────────────

LINE_NEEDS_ACCOUNT = "Every line needs an account."
ENTRY_NEEDS_DOCUMENT = "Choose the document this entry records."

# Disposition (triage): a "No entry required" choice must say why.
NO_ENTRY_NEEDS_REASON = "Say why this document needs no entry (1–200 characters)."


def out_of_balance(difference_cents: int) -> str:
    """Debits ≠ credits. ``difference_cents`` is the absolute gap."""
    return f"This entry is out of balance by {money.format_dollars(abs(difference_cents))}."


def line_needs_party(party_kind: str = "customer") -> str:
    """A control-account line with no party. ``party_kind`` is e.g. "customer"/"supplier"."""
    return f"Choose a {party_kind} for this line."


def date_outside_period(period_label: str) -> str:
    """``period_label`` is built from the pack, e.g. "December 1–31"."""
    return f"This date is outside {period_label}."


# ── Money parser (keyed by money.MoneyError.reason) ─────────────────────────────────────

MONEY_ERRORS: dict[str, str] = {
    money.EMPTY: "Enter an amount like 1,234.50.",
    money.NOT_A_NUMBER: "Enter an amount like 1,234.50.",
    money.MISPLACED_COMMA: "Enter an amount like 1,234.50.",
    money.TOO_MANY_DECIMALS: "Enter an amount with at most two decimal places.",
    money.NEGATIVE: "Enter an amount greater than zero.",
    money.ZERO: "Enter an amount greater than zero.",
    money.TOO_LARGE: "Enter an amount no larger than $99,999,999.99.",
}


def money_error(reason: str) -> str:
    return MONEY_ERRORS.get(reason, MONEY_ERRORS[money.NOT_A_NUMBER])


# ── Statements (S5.5): mechanical checks only, never a judgement about the layout ───────

STATEMENT_NEEDS_SUBTOTAL_TYPE = "Choose what this subtotal is."
STATEMENT_HEADING_NEEDS_LABEL = "Give this heading a label."
STATEMENT_SAVED = "Statement saved."


# ── Posting and entry lifecycle (T6.4) ──────────────────────────────────────────────────

JOURNAL_ALREADY_POSTED = "This journal has already been posted."
ENTRY_ALREADY_SUBSIDIARY_POSTED = "This entry has already been posted to the subsidiary ledger."
JOURNAL_SUBSIDIARY_ALREADY_POSTED = (
    "Every entry in this journal is already posted to the subsidiary ledger."
)
ENTRY_IS_POSTED = "This entry has been posted. Reverse the posting to change it."


# ── Gating and read-only states ─────────────────────────────────────────────────────────

def checkpoint_gate(checkpoint_ordinal: int, stage_label: str) -> str:
    """e.g. "Pass checkpoint 2 before recording adjusting entries." """
    return f"Pass checkpoint {checkpoint_ordinal} before recording {stage_label}."


READ_ONLY_SUBMITTED = (
    "These books are read-only because the assignment has been submitted. Your work is saved."
)
READ_ONLY_CLOSED = (
    "These books are read-only because the deadline has passed. Your work is saved."
)
# A manual-variant assignment (I1.3): the instructor hands out the figures themselves, and until
# they do there is nothing for this student to record against. Saying "submitted" here, as this
# once did, was simply untrue.
WAITING_FOR_VARIANT = (
    "Your instructor has not given you your set of figures yet. You will be able to record as "
    "soon as they do."
)


# ── Staff, on a student's workspace (I2.4) ──────────────────────────────────────────────
# Staff-facing, but written to the same rule: it says what is true, not how the work is going.

def viewing_students_books(student_name: str) -> str:
    return f"Viewing {student_name}'s books. This is read-only."


def grading_batch_strings() -> dict[str, str]:
    """What the grading progress line may say. Rendered onto the page for batch.js (T8.6).

    Staff-facing, and still written to the same rule as everything else: it says what happened,
    never how the section is doing.
    """
    return {
        # The numbers are filled in by the script, which knows how far the run has got.
        "counting": "Graded {done} of {total}.",
        "stalled": "The rest could not be graded here. Try `flask grade assignment`.",
        "failed": "The run stopped early. What was graded is saved; press Grade to carry on.",
    }


def viewing_archived_books(student_name: str, archived_on: str) -> str:
    """Books that were archived and replaced with a fresh set (I1.12).

    Staff can still read them — that is the whole reason archiving is safe to offer — and the
    banner says plainly that this is not where the student is working now.
    """
    return (
        f"Archived on {archived_on}. These are {student_name}'s old books; they now work in a "
        "fresh set. This is read-only."
    )


# ── Checkpoints ─────────────────────────────────────────────────────────────────────────

CHECKPOINT_PASSED = "Checkpoint passed."
CHECKPOINT_LOCKED = "This checkpoint is locked. Please see your instructor."
CHECKPOINT_CLOSED = "This checkpoint has closed. Please see your instructor."


def checkpoint_not_passed(attempts_remaining: int) -> str:
    noun = "attempt" if attempts_remaining == 1 else "attempts"
    return f"Checkpoint not passed. {attempts_remaining} {noun} remain."


# ── Document picker cross-company hint (M3.6) ────────────────────────────────────────────

def no_document_here(filter_text: str, company_name: str) -> str:
    return f"No document matches '{filter_text}' in {company_name}'s documents."


def document_in_other_workspace(display_ref: str, other_company_name: str) -> str:
    """Appended to :func:`no_document_here` when the student has the doc open elsewhere."""
    return f"{display_ref} is in {other_company_name}, which you also have open."


# ── No-loss protocol banners (T7.4 / T7.5) ──────────────────────────────────────────────

NOT_SAVED_RETRYING = "Not saved yet — retrying"


def saved_at(time_label: str) -> str:
    return f"Saved {time_label}"


def cannot_reach_server(time_label: str) -> str:
    return (
        f"We can't reach the server. Your last save was at {time_label}. "
        "This entry is still on this page and saved in this browser. Keep this tab open."
    )


STALE_TAB = "These books were changed in another tab or window. Reload to see the latest."

SAVE_STUCK = "That did not save. Your entry is still on this page. Try again in a moment."


def save_banner_strings() -> dict[str, str]:
    """What the connection banner may say. Rendered onto the page for save.js (T7.4)."""
    return {
        "retrying": NOT_SAVED_RETRYING,
        "stale": STALE_TAB,
        "stuck": SAVE_STUCK,
        # The time is filled in by the script, which knows when the last save actually landed.
        "unreachable": cannot_reach_server("{time}"),
    }
