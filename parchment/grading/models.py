"""The grading engine's own types (T8.1). Pure dataclasses: no Flask, no database.

``StudentWork`` is everything the engine is allowed to see about one workspace. It is built by
``grading/snapshot.py`` from the database, or in tests from a key replay. The engine never issues
a query, so every component can be tested in milliseconds.

Points are floats because credit is given per document and per adjustment: one document out of
fifty-six is a fraction of a component's marks. They are rounded for display, never for maths.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..ledger.models import Snapshot

# Disposition choices, as the student's triage records them.
RECORD = "record"
NO_ENTRY = "no_entry"


@dataclass(frozen=True)
class StatementRow:
    """One row of a statement the student built (S5.5)."""

    kind: str  # heading | account | subtotal | total | blank
    label: str | None = None
    account_number: str | None = None
    subtotal_type: str | None = None
    amount_cents: int | None = None
    indent: int = 0


@dataclass
class StudentWork:
    """One workspace, as the engine sees it."""

    snapshot: Snapshot
    dispositions: dict[str, str] = field(default_factory=dict)  # document ref -> choice
    disposition_reasons: dict[str, str] = field(default_factory=dict)
    statements: dict[str, tuple[StatementRow, ...]] = field(default_factory=dict)

    def live_entries(self):
        """Entries that still stand: voided ones are kept but never graded."""
        return [entry for entry in self.snapshot.entries.values() if not entry.voided]

    def entries_for_document(self, document_ref: str):
        return [e for e in self.live_entries() if e.document_ref == document_ref]


@dataclass(frozen=True)
class EvidenceRow:
    """What the student did on one item, and what the rule credited them for (I3.2)."""

    item: str
    detail: str
    earned: float
    possible: float


@dataclass(frozen=True)
class ComponentResult:
    key: str
    label: str
    points: float
    max_points: float
    evidence: tuple[EvidenceRow, ...] = ()
    needs_review: bool = False
    review_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class DetectedSignature:
    """A designed error the engine recognised (T8.5). Diagnosis, never an accusation."""

    key: str
    label: str
    confident: bool  # False for the balance-delta fallback, which reports "possibly"


@dataclass(frozen=True)
class GradeResult:
    engine_version: str
    components: tuple[ComponentResult, ...]
    signatures: tuple[DetectedSignature, ...] = ()
    #: Differences from the key that no signature explains: (account number, cents).
    unexplained: tuple[tuple[str, int], ...] = ()

    def component(self, key: str) -> ComponentResult:
        for component in self.components:
            if component.key == key:
                return component
        raise KeyError(key)

    @property
    def total_points(self) -> float:
        return sum(c.points for c in self.components)

    @property
    def max_points(self) -> float:
        return sum(c.max_points for c in self.components)

    @property
    def needs_review(self) -> bool:
        return any(c.needs_review for c in self.components)
