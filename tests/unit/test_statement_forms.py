"""Parsing a statement the student built (S5.5, tension 7).

The app supplies the form and the account list; the student decides what goes where, in what
order, and what every figure is. Validation here is mechanical only: an account must exist in
this pack's chart, a subtotal must name one of the pack's subtotal types, a heading needs a
label, and an amount must be a readable amount. Nothing checks whether the statement is any
good — that is the grading engine's business, after submission.
"""

import pytest
from originalentry import messages
from originalentry.forms.statements import StatementContext, parse_statement


@pytest.fixture
def ctx():
    return StatementContext(
        statement_type="income_statement",
        title="Income Statement",
        account_numbers={"401", "601"},
        subtotal_types={"net_sales": "Net sales", "net_income": "Net income"},
    )


def _form(rows, **header):
    form = {f"header-{k}": v for k, v in header.items()}
    for i, row in enumerate(rows):
        for field, value in row.items():
            form[f"row-{i}-{field}"] = value
    return form


def test_rows_keep_their_order_and_wholly_blank_rows_are_dropped(ctx):
    result = parse_statement(
        _form(
            [
                {"kind": "heading", "label": "Revenue"},
                {"kind": "", "label": "", "account": "", "amount": ""},
                {"kind": "account", "account": "401", "amount": "1,680.00", "indent": "1"},
                {"kind": "subtotal", "subtotal_type": "net_sales", "amount": "1680"},
            ],
            title="Income Statement",
        ),
        ctx,
    )

    assert result.ok, result.errors
    kinds = [row.kind for row in result.command.rows]
    assert kinds == ["heading", "account", "subtotal"]
    assert result.command.rows[1].account_number == "401"
    assert result.command.rows[1].amount_cents == 168000
    assert result.command.rows[1].indent == 1
    assert result.command.rows[2].subtotal_type == "net_sales"
    assert result.command.header["title"] == "Income Statement"


def test_account_row_needs_an_account_from_this_chart(ctx):
    result = parse_statement(_form([{"kind": "account", "account": "999", "amount": "5"}]), ctx)

    assert not result.ok
    assert result.errors == [("row-0-account", messages.LINE_NEEDS_ACCOUNT)]


def test_subtotal_row_needs_a_type_the_pack_offers(ctx):
    result = parse_statement(
        _form([{"kind": "subtotal", "subtotal_type": "gross_profit", "amount": "5"}]), ctx
    )

    assert not result.ok
    assert result.errors == [("row-0-subtotal_type", messages.STATEMENT_NEEDS_SUBTOTAL_TYPE)]


def test_heading_needs_a_label(ctx):
    result = parse_statement(_form([{"kind": "heading", "label": "   "}]), ctx)

    assert not result.ok
    assert result.errors == [("row-0-label", messages.STATEMENT_HEADING_NEEDS_LABEL)]


def test_amount_in_parentheses_is_a_negative_figure(ctx):
    """A net loss is written in parentheses on paper, so the form accepts it that way."""
    result = parse_statement(
        _form([{"kind": "subtotal", "subtotal_type": "net_income", "amount": "(420.00)"}]), ctx
    )

    assert result.ok, result.errors
    assert result.command.rows[0].amount_cents == -42000


def test_unreadable_amount_reports_the_money_message(ctx):
    result = parse_statement(_form([{"kind": "account", "account": "401", "amount": "1.234"}]), ctx)

    assert not result.ok
    assert result.errors == [("row-0-amount", messages.money_error("too_many_decimals"))]


def test_a_row_may_be_left_without_a_figure_while_the_student_works(ctx):
    result = parse_statement(_form([{"kind": "account", "account": "601", "amount": ""}]), ctx)

    assert result.ok, result.errors
    assert result.command.rows[0].amount_cents is None
