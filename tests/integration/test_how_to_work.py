"""The page that says what a student is expected to do (S1.5).

The question that prompted it: on a document, "Record an entry" reads as though the app has just
recorded it. It has not. It marks the decision that this document needs an entry; the student
then chooses a journal and writes the lines themselves.

That ambiguity runs through the whole workspace. Nothing here happens on its own: entries are
written, postings are posted, checkpoints are asked. The ledgers and the trial balance are the
only things the app derives, and it derives them from what the student posted. A page that says
so, in order, is the difference between working and guessing.

It is held to the same rule as every other screen (A7): it explains the method, never whether
any figure is any good.
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

BANNED = re.compile(r"\b(correct|incorrect|right|wrong)\b", re.IGNORECASE)


@pytest.fixture
def workspace(session, client):
    pv = import_content(session, schema.load_pack(testco_alpha.PACK),
                        source_sha256=secrets.token_hex(32))
    variant_id = session.scalars(
        select(Variant.id).where(Variant.pack_version_id == pv.id)).first()
    section = Section(name="Sec", join_code=f"H{secrets.token_hex(3).upper()}")
    student = User(email=f"hw-{secrets.token_hex(3)}@example.edu", role="student",
                   given_name="Ada", family_name="Sowande")
    instructor = User(email=f"hi-{secrets.token_hex(3)}@example.edu", role="instructor")
    session.add_all([section, student, instructor])
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
    return ws, student, instructor


def _page(client, ws) -> str:
    return client.get(f"/w/{ws.public_id}/testco-alpha/how-to").get_data(as_text=True)


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def test_a_student_can_open_it(client, workspace):
    ws, student, _ = workspace
    client.sign_in(student)

    response = client.get(f"/w/{ws.public_id}/testco-alpha/how-to")

    assert response.status_code == 200


def test_it_is_in_the_workspace_navigation(client, workspace):
    """A page nobody can find is a page nobody reads."""
    ws, student, _ = workspace
    client.sign_in(student)

    body = client.get(f"/w/{ws.public_id}/testco-alpha/").get_data(as_text=True)

    assert f"/w/{ws.public_id}/testco-alpha/how-to" in body


def test_it_answers_what_record_an_entry_actually_does(client, workspace):
    """The question that prompted the page."""
    ws, student, _ = workspace
    client.sign_in(student)

    text = _text(_page(client, ws)).lower()

    assert "record an entry" in text
    assert "no entry required" in text
    # It has to say plainly that the button does not write the entry.
    assert "does not" in text or "not record" in text


def test_it_says_posting_is_something_the_student_does(client, workspace):
    ws, student, _ = workspace
    client.sign_in(student)

    text = _text(_page(client, ws)).lower()

    assert "post" in text
    assert "nothing posts itself" in text or "does not post" in text


def test_it_says_which_things_the_app_works_out_for_itself(client, workspace):
    """Ledgers and the trial balance are derived; a student who tries to type them is lost."""
    ws, student, _ = workspace
    client.sign_in(student)

    text = _text(_page(client, ws)).lower()

    assert "ledger" in text
    assert "trial balance" in text
    assert "derive" in text or "works out" in text or "builds" in text


def test_it_covers_the_whole_way_through(client, workspace):
    ws, student, _ = workspace
    client.sign_in(student)

    text = _text(_page(client, ws)).lower()

    for word in ("document", "journal", "post", "checkpoint", "submit"):
        assert word in text, word


def test_the_steps_are_numbered_and_in_order(client, workspace):
    ws, student, _ = workspace
    client.sign_in(student)

    body = _page(client, ws)

    assert "<ol" in body
    assert body.index("Documents") < body.index("Submit")


def test_it_never_says_whether_the_work_is_any_good(client, workspace):
    """A7 reaches this page as much as any other."""
    ws, student, _ = workspace
    client.sign_in(student)

    assert not BANNED.search(_text(_page(client, ws)))


def test_staff_can_read_it_too(client, workspace):
    ws, _, instructor = workspace
    client.sign_in(instructor)

    assert client.get(f"/w/{ws.public_id}/testco-alpha/how-to").status_code == 200
