"""The statement builder end to end, through the same form endpoints the browser uses (T17.1).

These exercise the glue the service tests cannot see: the routes, the request context and the
templates with real data. The harness binds Flask-SQLAlchemy's session to the test connection,
so a request writes inside the test transaction and nothing persists.
"""

import pytest
from parchment.models import Assignment, Section, StatementLine, User, Variant, Workspace
from parchment.packs import schema
from parchment.packs.importer import import_content
from parchment.services.statements import load_draft
from sqlalchemy import func, select

from tests.packs import testco_alpha

pytestmark = pytest.mark.db


@pytest.fixture
def workspace(session, client):
    pv = import_content(session, schema.load_pack(testco_alpha.PACK), source_sha256="r" * 64)
    variant = session.scalars(select(Variant).where(Variant.pack_version_id == pv.id)).first()
    section = Section(name="Sec", join_code="route-join")
    student = User(email="route@example.edu")
    session.add_all([section, student])
    session.flush()
    asg = Assignment(section_id=section.id, title="December", company_policy="fixed",
                     fixed_pack_version_id=pv.id)
    session.add(asg)
    session.flush()
    ws = Workspace(assignment_id=asg.id, student_id=student.id, pack_version_id=pv.id,
                   variant_id=variant.id, status="in_progress")
    session.add(ws)
    session.flush()
    client.sign_in(student)
    return ws


def _url(workspace, suffix=""):
    return f"/w/{workspace.public_id}/testco-alpha/statements{suffix}"


def test_the_builder_opens_with_the_pack_form_and_the_students_own_figures(client, workspace):
    response = client.get(_url(workspace, "/income_statement"))

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Income Statement" in body
    assert "Net income" in body          # the pack's subtotal vocabulary
    assert "Accounts Receivable" in body  # their own ledger, in the side panel


def test_saving_rows_keeps_them_for_the_next_visit(client, workspace, session):
    response = client.post(_url(workspace, "/income_statement"), data={
        "header-title": "Income Statement",
        "row-0-kind": "heading", "row-0-label": "Revenue",
        "row-1-kind": "account", "row-1-account": "401", "row-1-amount": "5,000.00",
        "row-1-indent": "1",
        "row-2-kind": "subtotal", "row-2-subtotal_type": "net_income", "row-2-amount": "(420.00)",
    }, follow_redirects=True)

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Statement saved." in body
    assert 'value="5,000.00"' in body      # the row comes back as the student left it
    assert 'value="-420.00"' in body

    draft = load_draft(session, workspace, "income_statement")
    assert [line.kind for line in draft.lines] == ["heading", "account", "subtotal"]


def test_a_refused_save_keeps_every_row_on_the_page(client, workspace, session):
    response = client.post(_url(workspace, "/income_statement"), data={
        "row-0-kind": "account", "row-0-account": "401", "row-0-amount": "1.234",
        "row-1-kind": "heading", "row-1-label": "Revenue",
    })

    assert response.status_code == 422
    body = response.get_data(as_text=True)
    assert "Enter an amount with at most two decimal places." in body
    assert 'value="1.234"' in body     # nothing is retyped
    assert 'value="Revenue"' in body
    assert session.execute(
        select(func.count()).select_from(StatementLine)
        .where(StatementLine.workspace_id == workspace.id)
    ).scalar_one() == 0


def test_the_index_shows_which_statements_have_rows(client, workspace):
    client.post(_url(workspace, "/income_statement"),
                data={"row-0-kind": "heading", "row-0-label": "Revenue"})

    body = client.get(_url(workspace)).get_data(as_text=True)

    assert "Income Statement" in body
    assert "1 row" in body


def test_another_students_workspace_is_not_found(client, workspace, session):
    intruder = User(email="intruder@example.edu")
    session.add(intruder)
    session.flush()
    client.sign_in(intruder)

    assert client.get(_url(workspace, "/income_statement")).status_code == 404
