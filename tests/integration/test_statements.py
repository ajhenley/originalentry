"""Statement drafts (S5.4–S5.5, D4).

A draft is the student's own layout: rows in their order, with their figures. Saving replaces
the rows in place and bumps the draft's version (tension 9: drafts are overwritten, accounting
records are not). Every row stays scoped to the workspace's pack version.
"""

import pytest
from parchment.forms.statements import RowCommand, StatementCommand
from parchment.models import (
    Account,
    Assignment,
    Section,
    StatementLine,
    User,
    Variant,
    Workspace,
)
from parchment.packs import schema
from parchment.packs.importer import import_content
from parchment.services import WriteRefused, workspace_write
from parchment.services.statements import (
    draft_rows,
    load_draft,
    own_figures,
    save_statement,
    statement_counts,
)
from parchment.services.submit import submit_workspace
from sqlalchemy import func, select

from tests.packs import testco_alpha

pytestmark = pytest.mark.db


def _seed(session, join_code="stmt-join", email="stmt@example.edu"):
    pv = import_content(session, schema.load_pack(testco_alpha.PACK), source_sha256="s" * 64)
    variant = session.scalars(select(Variant).where(Variant.pack_version_id == pv.id)).first()
    section = Section(name="Sec", join_code=join_code)
    student = User(email=email)
    session.add_all([section, student])
    session.flush()
    asg = Assignment(section_id=section.id, title="Dec", company_policy="fixed",
                     fixed_pack_version_id=pv.id)
    session.add(asg)
    session.flush()
    ws = Workspace(assignment_id=asg.id, student_id=student.id, pack_version_id=pv.id,
                   variant_id=variant.id, status="in_progress")
    session.add(ws)
    session.flush()
    return ws, student


def _command(rows, statement_type="income_statement"):
    return StatementCommand(
        statement_type=statement_type,
        header={"title": "Income Statement"},
        rows=rows,
    )


def _save(session, ws, student, command):
    return workspace_write(session, ws.public_id, student, activity_kind="statement",
                           mutate=lambda s, w: save_statement(s, w, command))


def _line_count(session, ws):
    return session.execute(
        select(func.count()).select_from(StatementLine).where(StatementLine.workspace_id == ws.id)
    ).scalar_one()


def test_saved_rows_come_back_in_the_student_order(session):
    ws, student = _seed(session)

    _save(session, ws, student, _command([
        RowCommand(kind="heading", label="Revenue"),
        RowCommand(kind="account", account_number="401", amount_cents=168000, indent=1),
        RowCommand(kind="subtotal", subtotal_type="net_income", amount_cents=-42000),
    ]))

    draft = load_draft(session, ws, "income_statement")
    assert draft is not None
    assert draft.version == 1
    assert [line.kind for line in draft.lines] == ["heading", "account", "subtotal"]
    assert [line.position for line in draft.lines] == [0, 1, 2]

    account_row = draft.lines[1]
    account_id = session.scalars(
        select(Account.id).where(Account.pack_version_id == ws.pack_version_id,
                                 Account.number == "401")
    ).one()
    assert account_row.account_id == account_id
    assert account_row.amount_cents == 168000
    assert draft.lines[2].amount_cents == -42000  # a loss, as the student wrote it
    assert draft.header["title"] == "Income Statement"


def test_saving_again_replaces_the_rows_and_bumps_the_version(session):
    ws, student = _seed(session)
    _save(session, ws, student, _command([
        RowCommand(kind="account", account_number="401", amount_cents=100),
        RowCommand(kind="account", account_number="611", amount_cents=200),
    ]))

    _save(session, ws, student, _command([
        RowCommand(kind="account", account_number="611", amount_cents=250),
    ]))

    draft = load_draft(session, ws, "income_statement")
    assert draft.version == 2
    assert _line_count(session, ws) == 1
    assert draft.lines[0].amount_cents == 250


def test_an_account_outside_this_chart_is_refused(session):
    ws, student = _seed(session)

    with pytest.raises(WriteRefused):
        _save(session, ws, student,
              _command([RowCommand(kind="account", account_number="999", amount_cents=100)]))

    assert _line_count(session, ws) == 0


def test_a_submitted_workspace_no_longer_accepts_a_statement(session):
    ws, student = _seed(session)
    workspace_write(session, ws.public_id, student, activity_kind="submit",
                    mutate=lambda s, w: submit_workspace(s, w))

    with pytest.raises(WriteRefused):
        _save(session, ws, student,
              _command([RowCommand(kind="account", account_number="401", amount_cents=100)]))

    assert _line_count(session, ws) == 0


def test_counts_report_which_statements_have_been_started(session):
    ws, student = _seed(session)
    assert statement_counts(session, ws) == {}

    _save(session, ws, student, _command([RowCommand(kind="heading", label="Revenue")]))

    assert statement_counts(session, ws) == {"income_statement": 1}


def test_draft_rows_render_account_numbers_and_figures_for_the_form(session):
    ws, student = _seed(session)
    _save(session, ws, student, _command([
        RowCommand(kind="account", account_number="401", amount_cents=168000, indent=1),
        RowCommand(kind="subtotal", subtotal_type="net_income", amount_cents=-42000),
        RowCommand(kind="blank"),
    ]))

    rows = draft_rows(session, ws, load_draft(session, ws, "income_statement"))

    assert rows[0]["account_number"] == "401"       # the number, not the row id
    assert rows[0]["amount"] == "1,680.00"          # ready to put back in the input
    assert rows[0]["indent"] == 1
    assert rows[1]["subtotal_type"] == "net_income"
    assert rows[1]["amount"] == "-420.00"
    assert rows[2]["amount"] == ""                  # a blank row carries no figure


def test_own_figures_come_from_the_students_own_ledger(session):
    ws, student = _seed(session)

    figures = own_figures(session, ws, "adjusted")

    # Nothing has been journalised yet, so these are the opening balances of this variant.
    assert figures, "a workspace with opening balances has figures to show"
    assert all(f["amount_cents"] != 0 for f in figures)
    assert {"number", "name", "amount_cents"} <= set(figures[0])
    numbers = [f["number"] for f in figures]
    assert numbers == sorted(numbers, key=lambda n: _sort_order(session, ws, n))


def _sort_order(session, ws, number):
    return session.scalars(
        select(Account.sort_order).where(Account.pack_version_id == ws.pack_version_id,
                                         Account.number == number)
    ).one()
