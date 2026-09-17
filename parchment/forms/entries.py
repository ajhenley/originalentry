"""Parse and validate a general-journal entry (T7, Part I §4).

Every refusal message comes from ``messages`` and never uses a banned word. The database
constraints (one-side CHECK, composite FKs, balance trigger) are the backstop; this is the first
line that gives the student a clear reason.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date

from .. import messages, money
from ..models import KIND_ADJUSTING, KIND_CLOSING, KIND_REGULAR

VALID_KINDS = (KIND_REGULAR, KIND_ADJUSTING, KIND_CLOSING)


@dataclass(frozen=True)
class AccountInfo:
    number: str
    subsidiary_kind: str | None


@dataclass
class EntryContext:
    journal_key: str
    accounts: dict[str, AccountInfo]  # number -> info (this pack's chart)
    party_codes: set[str]
    period_start: date
    period_end: date
    period_label: str  # e.g. "December 1–31"
    document_refs: set[str]


@dataclass(frozen=True)
class LineCommand:
    account_number: str
    party_code: str | None
    debit_cents: int
    credit_cents: int
    memo: str | None = None
    column_key: str | None = None


@dataclass
class EntryCommand:
    journal_key: str
    kind: str
    document_ref: str | None
    entry_date: date
    description: str | None
    lines: list[LineCommand]
    client_key: str


@dataclass
class ParseResult:
    command: EntryCommand | None = None
    errors: list[tuple[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.command is not None and not self.errors

    def add(self, field_name: str, message: str) -> None:
        self.errors.append((field_name, message))


def _line_indices(form) -> list[int]:
    seen: set[int] = set()
    for key in form:
        if key.startswith("line-") and key.endswith("-account"):
            try:
                seen.add(int(key.split("-")[1]))
            except (ValueError, IndexError):
                continue
    return sorted(seen)


def parse_general_entry(form, ctx: EntryContext) -> ParseResult:
    result = ParseResult()

    kind = (form.get("kind") or KIND_REGULAR).strip()
    if kind not in VALID_KINDS:
        kind = KIND_REGULAR

    entry_date = _parse_date(form.get("entry_date"), ctx, result)

    document_ref = (form.get("document_ref") or "").strip() or None
    if kind == KIND_REGULAR:
        if document_ref is None:
            result.add("document_ref", messages.ENTRY_NEEDS_DOCUMENT)
        elif document_ref not in ctx.document_refs:
            result.add("document_ref", messages.ENTRY_NEEDS_DOCUMENT)
    else:
        document_ref = None  # adjusting/closing entries have no document

    lines = _parse_lines(form, ctx, result)

    if len(lines) < 2 and not result.errors:
        result.add("lines", "An entry needs at least two lines.")

    if lines:
        total_debit = sum(line.debit_cents for line in lines)
        total_credit = sum(line.credit_cents for line in lines)
        if total_debit != total_credit:
            result.add("lines", messages.out_of_balance(abs(total_debit - total_credit)))

    if result.errors:
        return result

    result.command = EntryCommand(
        journal_key=ctx.journal_key,
        kind=kind,
        document_ref=document_ref,
        entry_date=entry_date,
        description=(form.get("description") or "").strip() or None,
        lines=lines,
        client_key=(form.get("client_key") or "").strip() or uuid.uuid4().hex,
    )
    return result


def _parse_date(raw: str | None, ctx: EntryContext, result: ParseResult) -> date | None:
    if not raw:
        result.add("entry_date", messages.date_outside_period(ctx.period_label))
        return None
    try:
        parsed = date.fromisoformat(raw.strip())
    except ValueError:
        result.add("entry_date", messages.date_outside_period(ctx.period_label))
        return None
    if not (ctx.period_start <= parsed <= ctx.period_end):
        result.add("entry_date", messages.date_outside_period(ctx.period_label))
        return None
    return parsed


def _parse_lines(form, ctx: EntryContext, result: ParseResult) -> list[LineCommand]:
    lines: list[LineCommand] = []
    for i in _line_indices(form):
        number = (form.get(f"line-{i}-account") or "").strip()
        party = (form.get(f"line-{i}-party") or "").strip() or None
        debit_raw = (form.get(f"line-{i}-debit") or "").strip()
        credit_raw = (form.get(f"line-{i}-credit") or "").strip()
        memo = (form.get(f"line-{i}-memo") or "").strip() or None

        # A wholly empty row is ignored (blank rows in the grid).
        if not number and not debit_raw and not credit_raw and not memo:
            continue

        if not number:
            result.add(f"line-{i}-account", messages.LINE_NEEDS_ACCOUNT)
            continue
        account = ctx.accounts.get(number)
        if account is None:
            result.add(f"line-{i}-account", messages.LINE_NEEDS_ACCOUNT)
            continue

        debit_cents, credit_cents = _parse_amount(i, debit_raw, credit_raw, result)
        if debit_cents is None:
            continue

        if account.subsidiary_kind and party is None:
            result.add(f"line-{i}-party", messages.line_needs_party(account.subsidiary_kind))
            continue
        if party is not None and party not in ctx.party_codes:
            result.add(f"line-{i}-party", messages.line_needs_party(
                account.subsidiary_kind or "customer"))
            continue

        lines.append(
            LineCommand(
                account_number=number,
                party_code=party,
                debit_cents=debit_cents,
                credit_cents=credit_cents,
                memo=memo,
            )
        )
    return lines


def _parse_amount(i: int, debit_raw: str, credit_raw: str, result: ParseResult):
    if debit_raw and credit_raw:
        result.add(f"line-{i}-debit", "A line is a debit or a credit, not both.")
        return None, None
    if not debit_raw and not credit_raw:
        result.add(f"line-{i}-debit", messages.money_error(money.ZERO))
        return None, None
    side_raw, is_debit = (debit_raw, True) if debit_raw else (credit_raw, False)
    field_name = f"line-{i}-{'debit' if is_debit else 'credit'}"
    try:
        cents = money.parse_money(side_raw)
    except money.MoneyError as exc:
        result.add(field_name, messages.money_error(exc.reason))
        return None, None
    return (cents, 0) if is_debit else (0, cents)
