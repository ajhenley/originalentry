"""Adjusting and closing (T8.2, tension 8).

``adjustment_form`` marks the shape of each adjustment — which accounts, on which side — and
ignores the figure entirely, so a student who understood the adjustment but worked the number out
from a balance they had already got wrong keeps these marks.

``adjustment_amounts`` marks only the figures the key calls ``independent``: those a student can
work out from the documents and the policies alone. A ``dependent`` figure is shown to the grader
beside the student's own base balance and is not scored automatically.

``closing`` reads the student's own post-closing ledger: every temporary account cleared, income
summary empty, and retained earnings moved by their own net income less their own drawings.
"""

from __future__ import annotations

from ...ledger import engine
from ...ledger.models import ADJUSTING, CLOSING
from ...money import format_cents
from ..models import ComponentResult, EvidenceRow, StudentWork

# Account types closed out at the end of the period, and those that close straight to equity.
TEMPORARY_TYPES = frozenset(
    {"revenue", "contra_revenue", "expense", "cost_of_goods_sold", "other_income", "other_expense"}
)
DRAWING_TYPES = frozenset({"dividends", "drawings"})


def adjustment_form(work: StudentWork, pack, key, points: float) -> ComponentResult:
    adjustments = list(key.adjustments)
    per_adjustment = points / len(adjustments) if adjustments else 0.0
    student = _student_adjustments(work)
    evidence: list[EvidenceRow] = []
    reasons: list[str] = []
    earned = 0.0
    matched_entries: set[int] = set()

    for adjustment in adjustments:
        wanted = {(p.account, p.side) for p in adjustment.pattern}
        hits = [entry_id for entry_id, shape in student.items() if shape == wanted]
        if len(hits) > 1:
            reasons.append(f"More than one adjusting entry has the shape of {adjustment.label}.")
        if hits:
            earned += per_adjustment
            matched_entries.add(hits[0])
            detail = "Recorded with these accounts, on these sides."
        else:
            detail = "No adjusting entry uses these accounts on these sides."
        evidence.append(
            EvidenceRow(adjustment.label, detail, per_adjustment if hits else 0.0, per_adjustment)
        )

    for entry_id in student:
        if entry_id not in matched_entries:
            reasons.append(f"Adjusting entry {entry_id} matches none of the key's adjustments.")

    return ComponentResult(
        "adjustment_form", "Adjustments (form)", earned, points, tuple(evidence),
        needs_review=bool(reasons), review_reasons=tuple(reasons),
    )


def adjustment_amounts(work: StudentWork, pack, key, points: float) -> ComponentResult:
    independent = [a for a in key.adjustments if a.amount_basis == "independent"]
    dependent = [a for a in key.adjustments if a.amount_basis != "independent"]
    evidence: list[EvidenceRow] = []
    reasons: list[str] = []
    earned = 0.0

    per_adjustment = points / len(independent) if independent else 0.0
    student = _student_adjustments(work)
    amounts = _student_adjustment_amounts(work)

    for adjustment in independent:
        wanted = {(p.account, p.side) for p in adjustment.pattern}
        hits = [entry_id for entry_id, shape in student.items() if shape == wanted]
        if not hits:
            evidence.append(
                EvidenceRow(adjustment.label, "No adjusting entry to read a figure from.",
                            0.0, per_adjustment)
            )
            continue
        recorded = amounts[hits[0]]
        hit = recorded == adjustment.amount
        earned += per_adjustment if hit else 0.0
        evidence.append(
            EvidenceRow(
                adjustment.label,
                f"Recorded at {format_cents(recorded)}."
                if hit
                else f"Recorded at {format_cents(recorded)}; the key has "
                f"{format_cents(adjustment.amount or 0)}.",
                per_adjustment if hit else 0.0,
                per_adjustment,
            )
        )

    if dependent:
        balances = engine.balances(work.snapshot, "unadjusted")
        for adjustment in dependent:
            base = balances.get(adjustment.base_account or "", 0)
            reasons.append(
                f"{adjustment.label}: the figure follows from the student's own "
                f"{adjustment.base_account} balance ({format_cents(abs(base))})."
            )
            evidence.append(
                EvidenceRow(adjustment.label,
                            "This figure depends on the student's own earlier balance, so it is "
                            "left for the grader.", 0.0, 0.0)
            )

    return ComponentResult(
        "adjustment_amounts", "Adjustments (figures)", earned, points, tuple(evidence),
        needs_review=bool(reasons), review_reasons=tuple(reasons),
    )


def closing(work: StudentWork, pack, key, points: float) -> ComponentResult:
    if not any(entry.kind == CLOSING for entry in work.live_entries()):
        # An account that never held anything is not an account that was closed.
        return ComponentResult(
            "closing", "Closing", 0.0, points,
            (EvidenceRow("Closing", "No closing entries have been recorded.", 0.0, points),),
        )

    snapshot = work.snapshot
    after = engine.balances(snapshot, "post_closing")
    before = engine.balances(snapshot, "adjusted")

    to_clear = [
        number
        for number, account in snapshot.accounts.items()
        if account.account_type in TEMPORARY_TYPES or account.account_type in DRAWING_TYPES
    ]
    income_summary = snapshot.account_by_role("income_summary")
    if income_summary is not None:
        to_clear.append(income_summary.number)
    retained = snapshot.account_by_role("retained_earnings")

    checks = len(to_clear) + (1 if retained else 0)
    per_check = points / checks if checks else 0.0
    evidence: list[EvidenceRow] = []
    earned = 0.0

    for number in sorted(set(to_clear)):
        name = snapshot.accounts[number].name
        remaining = after.get(number, 0)
        cleared = remaining == 0
        earned += per_check if cleared else 0.0
        evidence.append(
            EvidenceRow(
                f"{number} {name}",
                "Cleared." if cleared else f"Still holds {format_cents(abs(remaining))}.",
                per_check if cleared else 0.0,
                per_check,
            )
        )

    if retained is not None:
        # Closing moves every temporary and drawing balance into retained earnings, so retained
        # earnings should shift by exactly the sum of those balances as the student left them
        # (debit-positive throughout: a profit is a net credit, and so a negative shift).
        expected_move = sum(
            before.get(number, 0)
            for number, account in snapshot.accounts.items()
            if account.account_type in TEMPORARY_TYPES or account.account_type in DRAWING_TYPES
        )
        actual_move = after.get(retained.number, 0) - before.get(retained.number, 0)
        ties = actual_move == expected_move
        earned += per_check if ties else 0.0
        evidence.append(
            EvidenceRow(
                f"{retained.number} {retained.name}",
                "Moved by the result of their own books."
                if ties
                else f"Moved by {format_cents(abs(actual_move))}; their own books give "
                f"{format_cents(abs(expected_move))}.",
                per_check if ties else 0.0,
                per_check,
            )
        )

    return ComponentResult("closing", "Closing", earned, points, tuple(evidence))


def _student_adjustments(work: StudentWork) -> dict[int, set[tuple[str, str]]]:
    """Each adjusting entry as the set of (account, side) it touches."""
    return {
        entry.id: {(line.account_number, line.side) for line in entry.lines}
        for entry in work.live_entries()
        if entry.kind == ADJUSTING
    }


def _student_adjustment_amounts(work: StudentWork) -> dict[int, int]:
    """The size of each adjusting entry: its total debits."""
    return {
        entry.id: sum(line.debit_cents for line in entry.lines)
        for entry in work.live_entries()
        if entry.kind == ADJUSTING
    }
