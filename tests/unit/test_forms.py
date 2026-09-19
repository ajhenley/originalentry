"""Journal-entry parsing and validation (forms/entries.py, Part I §4)."""

from datetime import date

from parchment.forms.entries import (
    AccountInfo,
    EntryContext,
    parse_general_entry,
    parse_special_entry,
)
from werkzeug.datastructures import MultiDict


def _ctx():
    return EntryContext(
        journal_key="general",
        accounts={
            "101": AccountInfo("101", None),
            "112": AccountInfo("112", "customer"),  # a control account
            "401": AccountInfo("401", None),
        },
        party_codes={"C-ONE"},
        period_start=date(2026, 12, 1),
        period_end=date(2026, 12, 31),
        period_label="December 1–31",
        document_refs={"INV-1"},
    )


def _form(**overrides):
    data = {
        "kind": "regular",
        "entry_date": "2026-12-02",
        "document_ref": "INV-1",
        "line-1-account": "112", "line-1-party": "C-ONE", "line-1-debit": "1,200.00",
        "line-2-account": "401", "line-2-credit": "1,200.00",
    }
    data.update(overrides)
    return MultiDict(data)


def test_valid_entry_parses():
    result = parse_general_entry(_form(), _ctx())
    assert result.ok
    cmd = result.command
    assert cmd.document_ref == "INV-1"
    assert cmd.entry_date == date(2026, 12, 2)
    assert [(line.account_number, line.debit_cents, line.credit_cents) for line in cmd.lines] == [
        ("112", 120000, 0), ("401", 0, 120000),
    ]
    assert cmd.client_key  # generated when the form omits one


def test_out_of_balance_is_refused():
    result = parse_general_entry(_form(**{"line-2-credit": "1,000.00"}), _ctx())
    assert not result.ok
    assert any("out of balance by $200.00" in m.lower() for _, m in result.errors)


def test_control_line_needs_a_party():
    result = parse_general_entry(_form(**{"line-1-party": ""}), _ctx())
    assert not result.ok
    assert any("customer" in m for _, m in result.errors)


def test_regular_entry_needs_a_document():
    result = parse_general_entry(_form(document_ref=""), _ctx())
    assert not result.ok
    assert any("document" in m.lower() for _, m in result.errors)


def test_adjusting_entry_needs_no_document():
    result = parse_general_entry(
        _form(kind="adjusting", document_ref="", **{"line-1-party": ""},
              **{"line-1-account": "101"}),
        _ctx(),
    )
    assert result.ok
    assert result.command.document_ref is None


def test_date_outside_period_refused():
    result = parse_general_entry(_form(entry_date="2027-01-05"), _ctx())
    assert not result.ok
    assert any("outside December" in m for _, m in result.errors)


def test_bad_amount_refused():
    result = parse_general_entry(_form(**{"line-1-debit": "12.345"}), _ctx())
    assert not result.ok
    assert result.errors


def test_blank_rows_are_ignored():
    form = _form()
    form["line-5-account"] = ""
    form["line-5-debit"] = ""
    result = parse_general_entry(form, _ctx())
    assert result.ok
    assert len(result.command.lines) == 2


# ── special journal (column grid, T6.1) ─────────────────────────────────────────────────

_COLUMNS = [
    {"key": "ar_dr", "label": "AR Dr", "side": "debit", "account": "112",
     "subsidiary_kind": "customer", "posts": "total"},
    {"key": "sales_cr", "label": "Sales Cr", "side": "credit", "account": "401",
     "posts": "total"},
    {"key": "other_cr", "label": "Other Cr", "side": "credit", "account": None,
     "posts": "individual"},
]


def _special_ctx():
    ctx = _ctx()
    ctx.journal_key = "sales"
    return ctx


def _special_form(**overrides):
    data = {
        "entry_date": "2026-12-02", "document_ref": "INV-1",
        "col-ar_dr-amount": "1,200.00", "col-ar_dr-party": "C-ONE",
        "col-sales_cr-amount": "1,200.00",
    }
    data.update(overrides)
    return MultiDict(data)


def test_special_entry_lines_carry_their_column_key():
    result = parse_special_entry(_special_form(), _special_ctx(), _COLUMNS)
    assert result.ok
    by_col = {line.column_key: line for line in result.command.lines}
    assert set(by_col) == {"ar_dr", "sales_cr"}
    assert by_col["ar_dr"].account_number == "112" and by_col["ar_dr"].debit_cents == 120000
    assert by_col["ar_dr"].party_code == "C-ONE"
    assert by_col["sales_cr"].credit_cents == 120000
    assert result.command.kind == "regular"


def test_special_control_column_needs_a_party():
    result = parse_special_entry(_special_form(**{"col-ar_dr-party": ""}), _special_ctx(), _COLUMNS)
    assert not result.ok
    assert any("customer" in m for _, m in result.errors)


def test_special_entry_must_balance():
    result = parse_special_entry(
        _special_form(**{"col-sales_cr-amount": "1,000.00"}), _special_ctx(), _COLUMNS)
    assert not result.ok
    assert any("out of balance" in m.lower() for _, m in result.errors)


def test_special_other_accounts_column_needs_an_account():
    # Fill the "Other accounts" column but name no account for it.
    form = _special_form(**{"col-other_cr-amount": "50.00"})
    result = parse_special_entry(form, _special_ctx(), _COLUMNS)
    assert not result.ok
    assert any("account" in m.lower() for _, m in result.errors)


def test_special_entry_needs_a_document():
    result = parse_special_entry(_special_form(document_ref=""), _special_ctx(), _COLUMNS)
    assert not result.ok
    assert any("document" in m.lower() for _, m in result.errors)
