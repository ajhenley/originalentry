"""The statements the student built (T8.2, tension 7).

Structure and figures are separate components on purpose. A student whose layout is sound keeps
those marks even when an earlier slip carried a wrong figure into every line — that is the
method-not-match rule where it matters most.

Structure reads the pack: which sections a statement may hold, in what order, and which subtotal
types it requires. Figures are compared with the student's **own** balances at the stage the pack
gives the statement, never with the key.
"""

from __future__ import annotations

from ...ledger import engine
from ...money import format_cents
from ..models import ComponentResult, EvidenceRow, StudentWork

ACCOUNT_ROW = "account"
SUBTOTAL_ROWS = ("subtotal", "total")


def statements_structure(work: StudentWork, pack, key, points: float) -> ComponentResult:
    definitions = list(pack.statements)
    per_statement = points / len(definitions) if definitions else 0.0
    evidence: list[EvidenceRow] = []
    reasons: list[str] = []
    earned = 0.0

    for definition in definitions:
        rows = work.statements.get(definition.type, ())
        if not rows:
            evidence.append(
                EvidenceRow(definition.title, "Not started.", 0.0, per_statement)
            )
            continue

        checks: list[tuple[str, bool, str]] = []
        seen: list[str] = []
        for row in rows:
            if row.kind != ACCOUNT_ROW or row.account_number is None:
                continue
            account = work.snapshot.accounts.get(row.account_number)
            section = account.statement_section if account else None
            belongs = section in definition.allowed_sections
            name = account.name if account else row.account_number
            checks.append((
                f"{row.account_number} {name}",
                belongs,
                "In a section this statement holds."
                if belongs
                else f"In {section or 'no section'}, which this statement does not hold.",
            ))
            if not belongs:
                reasons.append(
                    f"{definition.title}: {row.account_number} sits outside every section this "
                    "statement holds."
                )
            if row.account_number in seen:
                reasons.append(
                    f"{definition.title}: {row.account_number} appears more than once."
                )
            seen.append(row.account_number)

        subtotal_labels = {s.key: s.label for s in definition.subtotal_types}
        used = [row.subtotal_type for row in rows if row.kind in SUBTOTAL_ROWS]
        for required in definition.required_subtotals:
            present = required in used
            checks.append((
                subtotal_labels.get(required, required),
                present,
                "Shown." if present else "Not shown on this statement.",
            ))

        checks.append(("Order of sections", _sections_in_order(work, definition, rows),
                       "Sections follow the order this statement sets."))

        share = per_statement / len(checks) if checks else 0.0
        for item, passed, detail in checks:
            earned += share if passed else 0.0
            evidence.append(
                EvidenceRow(f"{definition.title}: {item}", detail, share if passed else 0.0, share)
            )

    return ComponentResult(
        "statements_structure", "Statements (structure)", earned, points, tuple(evidence),
        needs_review=bool(reasons), review_reasons=tuple(dict.fromkeys(reasons)),
    )


def statements_figures(work: StudentWork, pack, key, points: float) -> ComponentResult:
    definitions = list(pack.statements)
    per_statement = points / len(definitions) if definitions else 0.0
    evidence: list[EvidenceRow] = []
    reasons: list[str] = []
    earned = 0.0

    for definition in definitions:
        rows = work.statements.get(definition.type, ())
        if not rows:
            evidence.append(EvidenceRow(definition.title, "Not started.", 0.0, per_statement))
            continue

        own = engine.balances(work.snapshot, _stage(definition))
        figures = [row for row in rows if row.kind in (ACCOUNT_ROW, *SUBTOTAL_ROWS)]
        share = per_statement / len(figures) if figures else 0.0

        for index, row in enumerate(rows):
            if row.kind == ACCOUNT_ROW and row.account_number is not None:
                account = work.snapshot.accounts.get(row.account_number)
                name = account.name if account else row.account_number
                theirs = abs(own.get(row.account_number, 0))
                hit = row.amount_cents is not None and abs(row.amount_cents) == theirs
                earned += share if hit else 0.0
                evidence.append(
                    EvidenceRow(
                        f"{definition.title}: {row.account_number} {name}",
                        "Their own balance, as their ledger has it."
                        if hit
                        else f"Shown as {format_cents(row.amount_cents or 0)}; their own ledger "
                        f"has {format_cents(theirs)}.",
                        share if hit else 0.0,
                        share,
                    )
                )
            elif row.kind in SUBTOTAL_ROWS:
                label = _subtotal_label(definition, row.subtotal_type)
                hit = _subtotal_adds_up(rows, index, row.amount_cents)
                earned += share if hit else 0.0
                if not hit:
                    reasons.append(
                        f"{definition.title}: the {label} figure is not the sum or the net of the "
                        "figures above it."
                    )
                evidence.append(
                    EvidenceRow(
                        f"{definition.title}: {label}",
                        "Follows from the figures above it."
                        if hit
                        else f"Shown as {format_cents(row.amount_cents or 0)}.",
                        share if hit else 0.0,
                        share,
                    )
                )

    return ComponentResult(
        "statements_figures", "Statements (figures)", earned, points, tuple(evidence),
        needs_review=bool(reasons), review_reasons=tuple(dict.fromkeys(reasons)),
    )


def _stage(definition) -> str:
    """Which set of the student's own balances this statement reads. The pack decides."""
    return getattr(definition, "stage", "adjusted") or "adjusted"


def _subtotal_label(definition, subtotal_type) -> str:
    for subtotal in definition.subtotal_types:
        if subtotal.key == subtotal_type:
            return subtotal.label
    return subtotal_type or "Subtotal"


def _sections_in_order(work: StudentWork, definition, rows) -> bool:
    order = {section: i for i, section in enumerate(definition.allowed_sections)}
    positions = []
    for row in rows:
        if row.kind != ACCOUNT_ROW or row.account_number is None:
            continue
        account = work.snapshot.accounts.get(row.account_number)
        if account is None or account.statement_section not in order:
            continue
        positions.append(order[account.statement_section])
    return positions == sorted(positions)


def _subtotal_adds_up(rows, index: int, amount_cents: int | None) -> bool:
    """Arithmetic on the student's own figures: the sum, or the net, of what sits above.

    The block is everything since the previous subtotal or total; the running figures are
    everything above. Any of those four readings earns the mark, because the app takes no view on
    how a statement should be laid out — only on whether the arithmetic holds.
    """
    if amount_cents is None:
        return False

    block: list[int] = []
    for row in reversed(rows[:index]):
        if row.kind in SUBTOTAL_ROWS:
            break
        if row.kind == ACCOUNT_ROW and row.amount_cents is not None:
            block.append(row.amount_cents)

    running = [
        row.amount_cents
        for row in rows[:index]
        if row.kind == ACCOUNT_ROW and row.amount_cents is not None
    ]
    subtotals_above = [
        row.amount_cents
        for row in rows[:index]
        if row.kind in SUBTOTAL_ROWS and row.amount_cents is not None
    ]

    candidates = {
        sum(block),
        abs(_alternating_net(block)),
        sum(running),
        abs(_alternating_net(running)),
        sum(subtotals_above) if subtotals_above else None,
    }
    return abs(amount_cents) in {abs(c) for c in candidates if c is not None}


def _alternating_net(amounts: list[int]) -> int:
    """The net of a block read as "the first figure less the rest", as a statement reads."""
    if not amounts:
        return 0
    ordered = list(reversed(amounts))
    return ordered[0] - sum(ordered[1:])
