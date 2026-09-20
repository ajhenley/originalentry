"""Components that read the student's handling of the documents (T8.2).

``triage`` and ``journal_selection`` are wholly independent of every amount, so an error in
December's figures cannot reach them. ``entry_accuracy`` is the one component that compares
amounts with the key, and it does so **per document**, which is what stops one early mistake from
costing marks again and again (commitment 3).
"""

from __future__ import annotations

from ..models import NO_ENTRY, RECORD, ComponentResult, EvidenceRow, StudentWork


def triage(work: StudentWork, pack, key, points: float) -> ComponentResult:
    documents = sorted(key.triage)
    per_document = points / len(documents) if documents else 0.0
    evidence: list[EvidenceRow] = []
    earned = 0.0

    for ref in documents:
        expected = RECORD if key.triage[ref] else NO_ENTRY
        chose = work.dispositions.get(ref)
        if chose == expected:
            earned += per_document
            detail = f"Handled as {_label(chose)}."
        elif chose is None:
            detail = "Not handled."
        else:
            detail = f"Handled as {_label(chose)}; the key has {_label(expected)}."
        evidence.append(
            EvidenceRow(ref, detail, per_document if chose == expected else 0.0, per_document)
        )

    return ComponentResult("triage", "Document triage", earned, points, tuple(evidence))


def journal_selection(work: StudentWork, pack, key, points: float) -> ComponentResult:
    designated = sorted(key.designated_journal_documents)
    per_document = points / len(designated) if designated else 0.0
    evidence: list[EvidenceRow] = []
    reasons: list[str] = []
    earned = 0.0

    for ref in designated:
        expected = key.designated_journal_documents[ref]
        entries = work.entries_for_document(ref)
        if len(entries) > 1:
            reasons.append(f"{ref} has more than one entry that still stands.")
        if not entries:
            evidence.append(EvidenceRow(ref, "No entry recorded.", 0.0, per_document))
            continue
        used = entries[0].journal_key
        hit = used == expected
        earned += per_document if hit else 0.0
        evidence.append(
            EvidenceRow(
                ref,
                f"Recorded in {_journal_name(pack, used)}."
                if hit
                else f"Recorded in {_journal_name(pack, used)}; "
                f"the key uses {_journal_name(pack, expected)}.",
                per_document if hit else 0.0,
                per_document,
            )
        )

    return ComponentResult(
        "journal_selection", "Journal selection", earned, points, tuple(evidence),
        needs_review=bool(reasons), review_reasons=tuple(reasons),
    )


def entry_accuracy(work: StudentWork, pack, key, points: float) -> ComponentResult:
    expected_entries = list(key.expected_entries)
    per_document = points / len(expected_entries) if expected_entries else 0.0
    evidence: list[EvidenceRow] = []
    reasons: list[str] = []
    earned = 0.0

    for expected in expected_entries:
        ref = expected.document
        entries = work.entries_for_document(ref)
        if len(entries) > 1:
            reasons.append(f"{ref} has more than one entry that still stands.")
        if not entries:
            evidence.append(EvidenceRow(ref, "No entry recorded.", 0.0, per_document))
            continue

        wanted = _key_amounts(expected)
        got = _student_amounts(entries[0])
        share, detail = _compare(wanted, got)
        credit = per_document * share
        earned += credit
        evidence.append(EvidenceRow(ref, detail, credit, per_document))

    for ref, requires_entry in key.triage.items():
        if not requires_entry and work.entries_for_document(ref):
            reasons.append(f"{ref} has an entry, and the key records none for it.")

    return ComponentResult(
        "entry_accuracy", "Entry accounts and amounts", earned, points, tuple(evidence),
        needs_review=bool(reasons), review_reasons=tuple(reasons),
    )


def _compare(wanted: dict, got: dict) -> tuple[float, str]:
    """Half the credit for the accounts and sides, half for the figures on them."""
    keys = set(wanted) | set(got)
    if not keys:
        return 0.0, "No lines recorded."
    matched = set(wanted) & set(got)
    structure = len(matched) / len(keys)
    figures = sum(1 for k in matched if wanted[k] == got[k]) / len(keys)
    share = 0.5 * structure + 0.5 * figures

    if share == 1.0:
        return 1.0, "Accounts, parties, sides and figures all as the key has them."
    missing = sorted(_describe(k) for k in set(wanted) - set(got))
    extra = sorted(_describe(k) for k in set(got) - set(wanted))
    differing = sorted(_describe(k) for k in matched if wanted[k] != got[k])
    parts = []
    if missing:
        parts.append("the key also has " + ", ".join(missing))
    if extra:
        parts.append("this entry also has " + ", ".join(extra))
    if differing:
        parts.append("a different figure on " + ", ".join(differing))
    return share, "Credited for what lines up: " + "; ".join(parts) + "."


def _describe(line_key) -> str:
    account, party, side = line_key
    return f"{account} {side}" + (f" ({party})" if party else "")


def _key_amounts(expected) -> dict:
    """Lines merged by (account, party, side), so splitting a line is not a mistake (T8.3)."""
    merged: dict[tuple[str, str | None, str], int] = {}
    for line in expected.lines:
        side = "debit" if line.debit else "credit"
        amount = line.debit or line.credit or 0
        merged[(line.account, line.party, side)] = (
            merged.get((line.account, line.party, side), 0) + amount
        )
    return merged


def _student_amounts(entry) -> dict:
    merged: dict[tuple[str, str | None, str], int] = {}
    for line in entry.lines:
        line_key = (line.account_number, line.party_code, line.side)
        merged[line_key] = merged.get(line_key, 0) + line.amount_cents
    return merged


def _journal_name(pack, journal_key: str) -> str:
    for journal in pack.journals:
        if journal.key == journal_key:
            return journal.name
    return journal_key


def _label(choice: str) -> str:
    return "recorded" if choice == RECORD else "no entry required"
