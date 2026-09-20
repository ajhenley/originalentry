"""Parse and validate a statement the student built (S5.4–S5.5, tension 7).

The app supplies the form and the account list. The student chooses every row, its order and
every figure; the app does no arithmetic on statements and says nothing about what belongs
where. Validation is mechanical: an account must be in this pack's chart, a subtotal must name
one of the pack's subtotal types, a heading needs a label, and an amount must be readable.

A figure may be written in parentheses, the way a loss is written on paper, and is then stored
as a negative amount.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .. import messages, money

KIND_HEADING = "heading"
KIND_ACCOUNT = "account"
KIND_SUBTOTAL = "subtotal"
KIND_TOTAL = "total"
KIND_BLANK = "blank"

VALID_KINDS = (KIND_HEADING, KIND_ACCOUNT, KIND_SUBTOTAL, KIND_TOTAL, KIND_BLANK)
SUBTOTAL_KINDS = (KIND_SUBTOTAL, KIND_TOTAL)

MAX_INDENT = 2
MAX_AMOUNT_COLUMN = 3


@dataclass
class StatementContext:
    statement_type: str
    title: str
    account_numbers: set[str]  # this pack's chart
    subtotal_types: dict[str, str]  # key -> label, from the pack (tension 7)


@dataclass(frozen=True)
class RowCommand:
    kind: str
    label: str | None = None
    account_number: str | None = None
    subtotal_type: str | None = None
    amount_cents: int | None = None
    indent: int = 0
    amount_column: int = 1


@dataclass
class StatementCommand:
    statement_type: str
    header: dict[str, str]
    rows: list[RowCommand]


@dataclass
class ParseResult:
    command: StatementCommand | None = None
    errors: list[tuple[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.command is not None and not self.errors

    def add(self, field_name: str, message: str) -> None:
        self.errors.append((field_name, message))


def parse_statement(form, ctx: StatementContext) -> ParseResult:
    result = ParseResult()
    rows: list[RowCommand] = []

    for i in _row_indices(form):
        row = _parse_row(form, i, ctx, result)
        if row is not None:
            rows.append(row)

    if result.errors:
        return result

    result.command = StatementCommand(
        statement_type=ctx.statement_type,
        header=_parse_header(form, ctx),
        rows=rows,
    )
    return result


def _row_indices(form) -> list[int]:
    seen: set[int] = set()
    for key in form:
        if not key.startswith("row-"):
            continue
        try:
            seen.add(int(key.split("-")[1]))
        except (ValueError, IndexError):
            continue
    return sorted(seen)


def _parse_header(form, ctx: StatementContext) -> dict[str, str]:
    header = {}
    for name in ("title", "period"):
        value = (form.get(f"header-{name}") or "").strip()
        if value:
            header[name] = value
    header.setdefault("title", ctx.title)
    return header


def _parse_row(form, i: int, ctx: StatementContext, result: ParseResult) -> RowCommand | None:
    def value(name: str) -> str:
        return (form.get(f"row-{i}-{name}") or "").strip()

    kind = value("kind")
    label = value("label") or None
    account_number = value("account") or None
    subtotal_type = value("subtotal_type") or None
    amount_raw = value("amount")

    # A wholly empty row is one the student has not filled in yet.
    if not kind and not label and not account_number and not subtotal_type and not amount_raw:
        return None
    if kind not in VALID_KINDS:
        return None

    if kind == KIND_HEADING and label is None:
        result.add(f"row-{i}-label", messages.STATEMENT_HEADING_NEEDS_LABEL)
        return None
    if kind == KIND_ACCOUNT and account_number not in ctx.account_numbers:
        result.add(f"row-{i}-account", messages.LINE_NEEDS_ACCOUNT)
        return None
    if kind in SUBTOTAL_KINDS and subtotal_type not in ctx.subtotal_types:
        result.add(f"row-{i}-subtotal_type", messages.STATEMENT_NEEDS_SUBTOTAL_TYPE)
        return None

    amount_cents = None
    if amount_raw and kind not in (KIND_HEADING, KIND_BLANK):
        try:
            amount_cents = parse_statement_amount(amount_raw)
        except money.MoneyError as exc:
            result.add(f"row-{i}-amount", messages.money_error(exc.reason))
            return None

    return RowCommand(
        kind=kind,
        label=label,
        account_number=account_number if kind == KIND_ACCOUNT else None,
        subtotal_type=subtotal_type if kind in SUBTOTAL_KINDS else None,
        amount_cents=amount_cents,
        indent=_clamp(value("indent"), 0, MAX_INDENT, default=0),
        amount_column=_clamp(value("amount_column"), 1, MAX_AMOUNT_COLUMN, default=1),
    )


def parse_statement_amount(raw: str) -> int:
    """Statement figures may be written in parentheses for a negative, as on paper."""
    text = raw.strip()
    if text.startswith("(") and text.endswith(")"):
        return -money.parse_money(text[1:-1])
    return money.parse_money(text)


def _clamp(raw: str, low: int, high: int, *, default: int) -> int:
    try:
        return max(low, min(high, int(raw)))
    except (TypeError, ValueError):
        return default
