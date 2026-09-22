"""Amounts sit on the same row as the account they belong to (S3.7).

A journal is read across: this account, that figure. The account column listed every line, but
the debit and credit columns emitted only the lines carrying a figure, so each column closed up
its own gaps. An entry debiting line 1 and crediting line 2 put both figures on the first visual
row, against the wrong accounts.

It is worst on exactly the entries that matter most. A four-line entry with two debits and two
credits reads as though every account were debited and credited at once, and a compound entry
from a cash payments journal is unreadable.

So every column carries a cell for every line, empty where that line has nothing on that side.
"""

import re
import secrets
from datetime import date

import pytest
from originalentry.forms.entries import EntryCommand, LineCommand
from originalentry.models import Assignment, Section, User, Variant, Workspace
from originalentry.packs import schema
from originalentry.packs.importer import import_content
from originalentry.services import workspace_write
from originalentry.services.entries import record_entry
from sqlalchemy import select

from tests.packs import testco_alpha

pytestmark = pytest.mark.db


@pytest.fixture
def workspace(session, client):
    pv = import_content(session, schema.load_pack(testco_alpha.PACK),
                        source_sha256=secrets.token_hex(32))
    variant_id = session.scalars(
        select(Variant.id).where(Variant.pack_version_id == pv.id)).first()
    section = Section(name="Sec", join_code=f"L{secrets.token_hex(3).upper()}")
    student = User(email=f"jl-{secrets.token_hex(3)}@example.edu", role="student")
    session.add_all([section, student])
    session.flush()
    assignment = Assignment(section_id=section.id, title="December", company_policy="fixed",
                            fixed_pack_version_id=pv.id)
    session.add(assignment)
    session.flush()
    ws = Workspace(assignment_id=assignment.id, student_id=student.id, pack_version_id=pv.id,
                   variant_id=variant_id, status="in_progress")
    session.add(ws)
    session.flush()
    return ws, student


def _record(session, ws, student, lines, key="jl-1"):
    command = EntryCommand(
        journal_key="general", kind="regular", document_ref="INV-1",
        entry_date=date(2026, 12, 2), description=None, lines=lines, client_key=key,
    )
    return workspace_write(session, ws.public_id, student, activity_kind="save",
                           mutate=lambda s, w: record_entry(s, w, command))


def _cells(client, ws) -> list[str]:
    """The account, debit and credit cells of the first entry row."""
    body = client.get(
        f"/w/{ws.public_id}/testco-alpha/journals/general").get_data(as_text=True)
    row = body[body.index("<tbody"):]
    row = row[row.index("<tr"):row.index("</tr>")]
    tds = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
    return tds[2:5]          # after the entry number and the date


def _rows_in(cell: str) -> int:
    return len(re.findall(r"<li", cell))


def test_every_column_has_a_cell_for_every_line(client, session, workspace):
    """Two lines, a debit and a credit: three columns, two rows each."""
    ws, student = workspace
    _record(session, ws, student, [
        LineCommand("112", "C-ONE", 120000, 0),
        LineCommand("401", None, 0, 120000),
    ])
    session.commit()
    client.sign_in(student)

    accounts, debit, credit = _cells(client, ws)

    assert _rows_in(accounts) == 2
    assert _rows_in(debit) == 2
    assert _rows_in(credit) == 2


def test_a_figure_sits_on_its_own_line(client, session, workspace):
    """The debit belongs on row 1 and the credit on row 2, not both on row 1."""
    ws, student = workspace
    _record(session, ws, student, [
        LineCommand("112", "C-ONE", 120000, 0),
        LineCommand("401", None, 0, 120000),
    ])
    session.commit()
    client.sign_in(student)

    _, debit, credit = _cells(client, ws)
    debit_rows = re.findall(r"<li[^>]*>(.*?)</li>", debit, re.S)
    credit_rows = re.findall(r"<li[^>]*>(.*?)</li>", credit, re.S)

    assert "1,200.00" in debit_rows[0]
    assert "1,200.00" not in debit_rows[1]
    assert "1,200.00" not in credit_rows[0]
    assert "1,200.00" in credit_rows[1]


def test_a_compound_entry_keeps_every_line_in_step(client, session, workspace):
    """Four lines, two a side, which is where the old rendering was unreadable."""
    ws, student = workspace
    _record(session, ws, student, [
        LineCommand("112", "C-ONE", 50000, 0),
        LineCommand("154", None, 70000, 0),
        LineCommand("401", None, 0, 100000),
        LineCommand("301", None, 0, 20000),
    ])
    session.commit()
    client.sign_in(student)

    accounts, debit, credit = _cells(client, ws)

    assert _rows_in(accounts) == 4
    assert _rows_in(debit) == 4
    assert _rows_in(credit) == 4
    debit_rows = re.findall(r"<li[^>]*>(.*?)</li>", debit, re.S)
    assert "500.00" in debit_rows[0] and "700.00" in debit_rows[1]
    assert not re.search(r"\d", debit_rows[2]) and not re.search(r"\d", debit_rows[3])


# ── The same books, printed ─────────────────────────────────────────────────────────────
#
# The printed copy is built from the same lines and had the same fault, where it is worse: on
# paper there is no way to check what a figure was meant to line up with.

def test_the_printed_books_keep_the_columns_in_step(client, session, workspace):
    ws, student = workspace
    _record(session, ws, student, [
        LineCommand("112", "C-ONE", 50000, 0),
        LineCommand("154", None, 70000, 0),
        LineCommand("401", None, 0, 100000),
        LineCommand("301", None, 0, 20000),
    ])
    session.commit()
    client.sign_in(student)

    body = client.get(f"/w/{ws.public_id}/testco-alpha/print").get_data(as_text=True)
    row = body[body.index("<tbody"):]
    row = row[row.index("<tr"):row.index("</tr>")]
    accounts, debit, credit = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)[2:5]

    assert len(re.findall(r"<div", accounts)) == 4
    assert len(re.findall(r"<div", debit)) == 4
    assert len(re.findall(r"<div", credit)) == 4
