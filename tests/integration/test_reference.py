"""The Reference section (S1.5) and the marks export (I5.1).

A student needs the company's background, its policies, its chart of accounts and its payroll data
while they work — an adjustment cannot be made without them. The pack carries that material as
structured blocks, never HTML, so a pack can describe a company without being able to inject
anything into the page.

It must also never show another company's material: the screen reads only the pack version this
workspace is pinned to.
"""

import copy
import io
import json
import zipfile

import pytest
from parchment.models import Assignment, Section, User, Variant, Workspace
from parchment.packs.importing import import_pack_zip
from sqlalchemy import select

from tests.packs import testco_alpha

pytestmark = pytest.mark.db

REFERENCE = [
    {
        "key": "background",
        "title": "Company background",
        "blocks": [
            {"type": "p", "text": "TestCo Alpha sells kayak racks to outfitters."},
            {"type": "h", "text": "How we sell"},
            {"type": "ul", "items": ["On account, net 30", "Cash at the counter"]},
        ],
    },
    {
        "key": "policies",
        "title": "Accounting policies",
        "blocks": [
            {"type": "p", "text": "Equipment is depreciated on the straight line."},
            {"type": "table", "caption": "Useful lives",
             "headers": ["Asset", "Life"], "rows": [["Equipment", "8 years"]]},
        ],
    },
]


def _pack_with_reference(slug="testco-ref"):
    pack = copy.deepcopy(testco_alpha.PACK)
    pack["company"]["slug"] = slug
    pack["reference"] = copy.deepcopy(REFERENCE)
    return pack


def _zip(pack):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("pack.json", json.dumps(pack))
        archive.writestr("answer_keys/A.json", json.dumps(testco_alpha.KEY_A))
    buffer.seek(0)
    return buffer


@pytest.fixture
def workspace(session, client):
    instructor = User(email="ref-instructor@example.edu", role="instructor")
    session.add(instructor)
    session.flush()
    version = import_pack_zip(session, _zip(_pack_with_reference()), actor=instructor)
    variant_id = session.scalars(
        select(Variant.id).where(Variant.pack_version_id == version.id)
    ).first()
    section = Section(name="Sec", join_code="ref-join")
    student = User(email="ref-student@example.edu", given_name="Ola", family_name="Okoro")
    session.add_all([section, student])
    session.flush()
    assignment = Assignment(section_id=section.id, title="December", company_policy="fixed",
                            fixed_pack_version_id=version.id, mode="paper")
    session.add(assignment)
    session.flush()
    ws = Workspace(assignment_id=assignment.id, student_id=student.id,
                   pack_version_id=version.id, variant_id=variant_id, status="in_progress")
    session.add(ws)
    session.flush()
    client.sign_in(student)
    return ws, student, assignment, instructor


def _url(workspace, suffix=""):
    return f"/w/{workspace.public_id}/testco-ref/reference{suffix}"


def test_the_reference_lists_what_the_company_gives_you(client, workspace):
    ws, *_ = workspace

    body = client.get(_url(ws)).get_data(as_text=True)

    assert "Company background" in body
    assert "Accounting policies" in body
    assert "Chart of accounts" in body     # always offered, built from the pack's own accounts


def test_a_section_shows_its_blocks_as_the_pack_wrote_them(client, workspace):
    ws, *_ = workspace

    body = client.get(_url(ws, "/background")).get_data(as_text=True)

    assert "sells kayak racks to outfitters" in body
    assert "How we sell" in body
    assert "On account, net 30" in body


def test_a_table_block_becomes_a_table(client, workspace):
    ws, *_ = workspace

    body = client.get(_url(ws, "/policies")).get_data(as_text=True)

    assert "<table" in body
    assert "Useful lives" in body
    assert "8 years" in body


def test_the_chart_of_accounts_is_always_there(client, workspace):
    """Every pack has a chart, whether or not its author wrote a reference section for it."""
    ws, *_ = workspace

    body = client.get(_url(ws, "/chart-of-accounts")).get_data(as_text=True)

    assert "Accounts Receivable" in body
    assert "112" in body


def test_a_pack_that_carries_nothing_extra_still_has_its_chart(session, client):
    instructor = User(email="bare@example.edu", role="instructor")
    session.add(instructor)
    session.flush()
    bare = copy.deepcopy(testco_alpha.PACK)
    bare["company"]["slug"] = "testco-bare"
    version = import_pack_zip(session, _zip(bare), actor=instructor)
    variant_id = session.scalars(
        select(Variant.id).where(Variant.pack_version_id == version.id)
    ).first()
    section = Section(name="Sec", join_code="bare-join")
    student = User(email="bare-student@example.edu")
    session.add_all([section, student])
    session.flush()
    assignment = Assignment(section_id=section.id, title="December", company_policy="fixed",
                            fixed_pack_version_id=version.id)
    session.add(assignment)
    session.flush()
    ws = Workspace(assignment_id=assignment.id, student_id=student.id,
                   pack_version_id=version.id, variant_id=variant_id, status="in_progress")
    session.add(ws)
    session.flush()
    client.sign_in(student)

    body = client.get(f"/w/{ws.public_id}/testco-bare/reference").get_data(as_text=True)

    assert "Chart of accounts" in body
    assert "Company background" not in body


def test_a_section_this_company_does_not_have_is_not_found(client, workspace):
    ws, *_ = workspace

    assert client.get(_url(ws, "/payroll")).status_code == 404


def test_the_reference_is_reachable_from_every_workspace_page(client, workspace):
    ws, *_ = workspace

    body = client.get(f"/w/{ws.public_id}/testco-ref/documents").get_data(as_text=True)

    assert f"/w/{ws.public_id}/testco-ref/reference" in body


def test_marks_download_as_a_csv_the_gradebook_will_take(client, workspace):
    ws, student, assignment, instructor = workspace
    client.sign_in(instructor)

    response = client.get(f"/staff/grading/{assignment.public_id}/marks.csv")

    assert response.status_code == 200
    assert "text/csv" in response.headers["Content-Type"]
    assert "attachment" in response.headers["Content-Disposition"]
    header = response.get_data(as_text=True).splitlines()[0]
    assert header.split(",")[:4] == ["name", "email", "student_number", "points"]
    assert "late_hours" in header and "submission_status" in header


def test_the_canvas_preset_is_offered_too(client, workspace):
    _, _, assignment, instructor = workspace
    client.sign_in(instructor)

    response = client.get(f"/staff/grading/{assignment.public_id}/marks.csv?preset=canvas")

    assert response.status_code == 200
    assert "Student" in response.get_data(as_text=True).splitlines()[0]
