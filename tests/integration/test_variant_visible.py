"""Which version a student has, shown where it is needed (I1.3, A24).

Companies ship in versions with different figures, which is what stops a student working from a
classmate's numbers. The cost of that is a question nobody could answer from inside the app:
which version is this student on? The instructor guide puts it plainly - when a student queries a
mark, the first question is which packet they had - and the answer was in the database only.

It surfaces in three places, because three different people need it: the instructor scanning a
section, the grader marking one student against one key, and anyone looking at a set of books.
"""

import secrets

import pytest
from originalentry.models import Assignment, Section, User, Variant, Workspace
from originalentry.packs import schema
from originalentry.packs.importer import import_answer_keys, import_content
from sqlalchemy import select

from tests.packs import testco_alpha

pytestmark = pytest.mark.db


@pytest.fixture
def section(session, client):
    pv = import_content(session, schema.load_pack(testco_alpha.PACK),
                        source_sha256=secrets.token_hex(32))
    import_answer_keys(session, pv, {"A": schema.load_answer_key(testco_alpha.KEY_A)})
    variant = session.scalars(select(Variant).where(Variant.pack_version_id == pv.id)).first()
    sec = Section(name="Sec", join_code=f"V{secrets.token_hex(3).upper()}")
    student = User(email=f"vv-{secrets.token_hex(3)}@example.edu", role="student",
                   given_name="Ada", family_name="Sowande")
    instructor = User(email=f"vi-{secrets.token_hex(3)}@example.edu", role="instructor")
    session.add_all([sec, student, instructor])
    session.flush()
    assignment = Assignment(section_id=sec.id, title="December", company_policy="fixed",
                            fixed_pack_version_id=pv.id)
    session.add(assignment)
    session.flush()
    ws = Workspace(assignment_id=assignment.id, student_id=student.id, pack_version_id=pv.id,
                   variant_id=variant.id, status="in_progress")
    session.add(ws)
    session.flush()
    session.commit()
    return assignment, ws, student, instructor, variant.code


def test_progress_says_which_version_each_student_has(client, section):
    """The screen an instructor scans when a student asks a question about a figure."""
    assignment, _, _, instructor, code = section
    client.sign_in(instructor)

    body = client.get(f"/staff/progress/{assignment.public_id}").get_data(as_text=True)

    assert f"Version {code}" in body


def test_the_grading_screen_says_which_key_the_marks_came_from(client, section):
    assignment, ws, _, instructor, code = section
    client.sign_in(instructor)

    body = client.get(
        f"/staff/grading/{assignment.public_id}/{ws.public_id}").get_data(as_text=True)

    assert f"Version {code}" in body


def test_the_books_themselves_say_which_version_they_are(client, section):
    """So anyone looking at a set of books can tell, without asking the database."""
    _, ws, student, _, code = section
    client.sign_in(student)

    body = client.get(f"/w/{ws.public_id}/testco-alpha/").get_data(as_text=True)

    assert f"Version {code}" in body


def test_a_student_waiting_for_a_variant_is_not_told_they_have_one(client, session, section):
    """A manual-variant assignment hands them out later; until then there is nothing to show."""
    assignment, ws, student, instructor, _ = section
    ws.variant_id = None
    session.flush()
    session.commit()
    client.sign_in(instructor)

    body = client.get(f"/staff/progress/{assignment.public_id}").get_data(as_text=True)

    assert "Waiting for a variant" in body
