"""The order accounts appear in when you are picking one (S3.3).

The chart of accounts has an order of its own: assets, then liabilities, equity, revenue,
expenses, which is why it is numbered the way it is. That order is right when you are reading
the chart, and wrong when you are hunting for one account in a list of forty-two while looking
at a document that names it in words.

So the two are separated deliberately. Picking an account goes by name. Reading the chart, the
trial balance and the ledgers stays in chart order, because there the numbering is the point.
"""

import re
import secrets

import pytest
from originalentry.models import Assignment, Section, User, Variant, Workspace
from originalentry.packs import schema
from originalentry.packs.importer import import_content
from sqlalchemy import select

from tests.packs import testco_alpha

pytestmark = pytest.mark.db

# Chart order and alphabetical order differ for this pack, which is what makes the tests below
# able to tell them apart.
BY_NAME = ["Accounts Receivable", "Accumulated Depreciation", "Cash", "Depreciation Expense",
           "Equipment", "Income Summary", "Owner Capital", "Sales Revenue"]
BY_CHART = ["Cash", "Accounts Receivable", "Equipment", "Accumulated Depreciation",
            "Owner Capital", "Income Summary", "Sales Revenue", "Depreciation Expense"]


@pytest.fixture
def workspace(session, client):
    pv = import_content(session, schema.load_pack(testco_alpha.PACK),
                        source_sha256=secrets.token_hex(32))
    variant_id = session.scalars(
        select(Variant.id).where(Variant.pack_version_id == pv.id)).first()
    section = Section(name="Sec", join_code=f"A{secrets.token_hex(3).upper()}")
    student = User(email=f"ap-{secrets.token_hex(3)}@example.edu", role="student")
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
    session.commit()
    client.sign_in(student)
    return ws


def _options(body: str, select_name: str) -> list[str]:
    """The account names offered by one <select>, in the order they are offered."""
    block = body[body.index(f'name="{select_name}"'):]
    block = block[:block.index("</select>")]
    return [re.sub(r"\s+", " ", m).strip().split("·")[-1].strip()
            for m in re.findall(r"<option[^>]*>(.*?)</option>", block, re.S)
            if "·" in m]


def _new_entry(client, ws, key: str) -> str:
    return client.get(
        f"/w/{ws.public_id}/testco-alpha/journals/{key}/entries/new").get_data(as_text=True)


def test_the_general_journal_picker_is_alphabetical(client, workspace):
    assert _options(_new_entry(client, workspace, "general"), "line-1-account") == BY_NAME


def test_the_picker_still_offers_every_account(client, workspace):
    """A sort that drops or duplicates a row would be worse than the order it fixed."""
    offered = _options(_new_entry(client, workspace, "general"), "line-1-account")

    assert sorted(offered) == sorted(BY_CHART)


def test_the_general_ledger_keeps_chart_order(client, workspace):
    """Two orders, deliberately. Reading the ledgers the numbering is the point, and
    alphabetising them would destroy the trial balance they build towards."""
    body = client.get(
        f"/w/{workspace.public_id}/testco-alpha/ledgers/general").get_data(as_text=True)

    positions = [body.index(name) for name in BY_CHART if name in body]
    assert len(positions) > 3, "too few accounts on the page to tell the orders apart"
    assert positions == sorted(positions), "the trial balance is no longer in chart order"
