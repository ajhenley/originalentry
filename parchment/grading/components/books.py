"""Components that read the state of the student's own books (T8.2, tension 1).

Because the ledgers are derived, posting cannot be done *wrongly* in this app — only left undone.
So ``posting_completeness`` measures exactly that, and carries a small weight. The subsidiary
proof is internal consistency: the student's party totals against the student's own control
balance, never against the key.
"""

from __future__ import annotations

from ...ledger import engine
from ..models import ComponentResult, EvidenceRow, StudentWork


def posting_completeness(work: StudentWork, pack, key, points: float) -> ComponentResult:
    posted_general = _posted_ids(work.snapshot.general_postings)
    posted_subsidiary = _posted_ids(work.snapshot.subsidiary_postings)

    items: list[tuple[str, bool]] = []
    for entry in work.live_entries():
        items.append((f"Entry {entry.id} to the general ledger", entry.id in posted_general))
        if any(line.party_code for line in entry.lines):
            items.append(
                (f"Entry {entry.id} to the subsidiary ledger", entry.id in posted_subsidiary)
            )

    if not items:
        return ComponentResult(
            "posting_completeness", "Posting", 0.0, points,
            (EvidenceRow("Posting", "Nothing has been recorded yet.", 0.0, points),),
        )

    per_item = points / len(items)
    earned = sum(per_item for _, posted in items if posted)
    outstanding = [label for label, posted in items if not posted]
    detail = (
        "Everything recorded has been posted."
        if not outstanding
        else f"{len(outstanding)} of {len(items)} postings are still outstanding."
    )
    return ComponentResult(
        "posting_completeness", "Posting", earned, points,
        (EvidenceRow("Posting", detail, earned, points),),
    )


def subsidiary_agreement(work: StudentWork, pack, key, points: float) -> ComponentResult:
    if not work.live_entries():
        # Books with nothing in them agree with themselves. That is not worth marks.
        return ComponentResult(
            "subsidiary_agreement", "Subsidiary ledgers", 0.0, points,
            (EvidenceRow("Subsidiary ledgers", "Nothing has been recorded yet.", 0.0, points),),
        )

    kinds = sorted(
        {a.subsidiary_kind for a in work.snapshot.accounts.values() if a.subsidiary_kind}
    )
    if not kinds:
        return ComponentResult("subsidiary_agreement", "Subsidiary ledgers", points, points)

    per_kind = points / len(kinds)
    evidence: list[EvidenceRow] = []
    earned = 0.0
    for kind in kinds:
        proof = engine.subsidiary_proof(work.snapshot, kind)
        if proof.agrees:
            earned += per_kind
            detail = "The subsidiary total and the control account agree."
        else:
            detail = (
                "The subsidiary total and the control account differ by "
                f"{abs(proof.difference_cents) / 100:,.2f}."
            )
        evidence.append(EvidenceRow(kind, detail, per_kind if proof.agrees else 0.0, per_kind))

    return ComponentResult(
        "subsidiary_agreement", "Subsidiary ledgers", earned, points, tuple(evidence)
    )


def _posted_ids(postings) -> set[int]:
    return {entry_id for posting in postings for entry_id in posting.entry_ids}
