"""Naming the designed errors (T8.5).

The pack's key carries, per variant, a signature for each error the company was built to provoke.
Detection reads **the student's entry for one named document** first, because a company's
balances are touched by too many transactions to diagnose from a difference alone: any unrelated
slip on the same account would hide the error, and the instructor would never hear about it.

Only an error with no single document behind it — a missed adjustment, say — falls back to the
balances, and it is then reported as a possibility rather than a finding.

This is diagnosis for the instructor. It changes no mark unless the pack says so, it never
reaches the student, and it never accuses anyone of anything (T8.8).
"""

from __future__ import annotations

from ..ledger import engine
from .models import DetectedSignature, StudentWork

ENTRY_LINE = "entry_line"
ENTRY_AMOUNT = "entry_amount"
BALANCE_DELTA = "balance_delta"


def detect(work: StudentWork, pack, key) -> tuple[tuple[DetectedSignature, ...],
                                                  tuple[tuple[str, int], ...]]:
    """Return the signatures found, and the differences no signature explains."""
    if not work.live_entries():
        # There is nothing to diagnose in books with nothing in them, and the balances of an
        # untouched workspace would otherwise match any signature that names untouched accounts.
        return (), ()

    deltas = _deltas(work, key)
    found: list[DetectedSignature] = []
    explained_documents: set[str] = set()

    for signature in key.error_signatures:
        detector = signature.detect or {}
        kind = detector.get("type")
        if kind == ENTRY_LINE and _entry_has_line(work, detector):
            found.append(DetectedSignature(signature.key, signature.label, True))
            explained_documents.add(detector["document"])
        elif kind == ENTRY_AMOUNT and _entry_has_amount(work, detector):
            found.append(DetectedSignature(signature.key, signature.label, True))
            explained_documents.add(detector["document"])

    # What those documents account for is taken off the table before the balances are read, so a
    # fallback signature is not matched by a difference that is already understood.
    for document_ref in explained_documents:
        for account, amount in _document_difference(work, key, document_ref).items():
            deltas[account] = deltas.get(account, 0) - amount

    for signature in key.error_signatures:
        detector = signature.detect or {}
        if detector.get("type") != BALANCE_DELTA:
            continue
        wanted = {account: int(amount) for account, amount in detector.get("deltas", {}).items()}
        if wanted and all(deltas.get(account, 0) == amount for account, amount in wanted.items()):
            found.append(DetectedSignature(signature.key, signature.label, False))
            for account, amount in wanted.items():
                deltas[account] = deltas.get(account, 0) - amount

    unexplained = tuple(
        sorted((account, amount) for account, amount in deltas.items() if amount != 0)
    )
    return tuple(found), unexplained


def _deltas(work: StudentWork, key) -> dict[str, int]:
    """The student's adjusted balances less the key's, account by account (debit-positive)."""
    expected = key.expected_balances.get("adjusted", {})
    theirs = engine.balances(work.snapshot, "adjusted")
    return {
        account: theirs.get(account, 0) - expected.get(account, 0)
        for account in set(expected) | set(theirs)
    }


def _entry_has_line(work: StudentWork, detector: dict) -> bool:
    for entry in work.entries_for_document(detector.get("document", "")):
        for line in entry.lines:
            if line.account_number == detector.get("account") and line.side == detector.get("side"):
                return True
    return False


def _entry_has_amount(work: StudentWork, detector: dict) -> bool:
    wanted = int(detector.get("amount", 0))
    for entry in work.entries_for_document(detector.get("document", "")):
        total = sum(
            line.amount_cents
            for line in entry.lines
            if line.account_number == detector.get("account") and line.side == detector.get("side")
        )
        if total and total == wanted:
            return True
    return False


def _document_difference(work: StudentWork, key, document_ref: str) -> dict[str, int]:
    """How this document's entry differs from the key's, per account (debit-positive)."""
    difference: dict[str, int] = {}
    for expected in key.expected_entries:
        if expected.document != document_ref:
            continue
        for line in expected.lines:
            amount = (line.debit or 0) - (line.credit or 0)
            difference[line.account] = difference.get(line.account, 0) - amount
    for entry in work.entries_for_document(document_ref):
        for line in entry.lines:
            amount = line.debit_cents - line.credit_cents
            difference[line.account_number] = difference.get(line.account_number, 0) + amount
    return difference
