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


# ── Checkpoints ─────────────────────────────────────────────────────────────────────────

CHECKPOINT_PASSED = "Checkpoint passed."
CHECKPOINT_LOCKED = "This checkpoint is locked. Please see your instructor."


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
