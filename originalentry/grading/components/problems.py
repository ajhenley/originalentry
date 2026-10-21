"""The best N of a chapter's problems (T8.2).

Every other component divides its points across *every* document in the pack
(``documents.entry_accuracy``, and see ``documents.py`` line 75). That is exactly wrong for a
chapter problem set: a student who works twelve problems when six count would be marked out of
twelve, so practising beyond the minimum would cost marks -- the one thing this feature promises
it cannot do.

So this component selects instead of dividing. It scores every problem the same way
``entry_accuracy`` scores a document -- the same helpers, so the two can never drift apart -- then
drops the problems whose answer has been revealed, and keeps the best N of what is left.

A new component rather than an option on an existing one: no practice set's marks may move by a
point, and the safest way to guarantee that is for their code not to change.
"""

from __future__ import annotations

from ..models import ComponentResult, EvidenceRow, StudentWork
from .documents import _compare, _key_amounts, _student_amounts

#: A revealed problem carries this instead of a share, so it is excluded from the ranking rather
#: than ranked last -- which would let it take one of the N slots and silently cost a mark.
REVEALED = None


def problems_best_n(work: StudentWork, pack, key, points: float) -> ComponentResult:
    scores: dict[str, float | None] = {}
    details: dict[str, str] = {}
    reasons: list[str] = []

    for expected in key.expected_entries:
        ref = expected.document
        entries = work.entries_for_document(ref)
        if len(entries) > 1:
            reasons.append(f"{ref} has more than one entry that still stands.")

        if ref in work.revealed:
            scores[ref] = REVEALED
            details[ref] = "Answer revealed; this problem no longer counts toward the mark."
        elif not entries:
            scores[ref] = 0.0
            details[ref] = "No entry recorded."
        else:
            scores[ref], details[ref] = _compare(_key_amounts(expected),
                                                 _student_amounts(entries[0]))

    counting = {ref: share for ref, share in scores.items() if share is not REVEALED}

    required = work.problems_required
    if required is None:
        # Task 6 refuses an assignment that does not say. If one reaches grading anyway, marking
        # out of every problem is defensible and marking out of nothing is not -- but a human has
        # to be told either way, because the alternative is a whole section's marks quietly
        # computed against the wrong denominator.
        required = len(counting)
        reasons.append(
            "The assignment does not say how many problems count (problems_required is not set), "
            "so every problem has been counted."
        )

    # Ties broken by ref so the same work always earns the same mark.
    ranked = sorted(counting, key=lambda ref: (-counting[ref], ref))
    chosen = set(ranked[:required]) if required > 0 else set()
    per_problem = points / required if required > 0 else 0.0

    earned = sum(counting[ref] * per_problem for ref in chosen)

    evidence = tuple(
        EvidenceRow(
            ref,
            details[ref] if ref in chosen or scores[ref] is REVEALED
            else f"{details[ref]} Not among the {required} that count toward the mark.",
            counting[ref] * per_problem if ref in chosen else 0.0,
            per_problem if ref in chosen else 0.0,
        )
        for ref in scores
    )

    return ComponentResult(
        "problems_best_n", "Chapter problems", earned, points, evidence,
        needs_review=bool(reasons), review_reasons=tuple(reasons),
    )
