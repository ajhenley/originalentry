"""The account menu: your workspaces, and the way out (S6.6).

Signing out was reachable from the student's home page and the staff console, and nowhere else.
A student who was actually working — inside their books, which is where they spend the whole
assignment — had no way to leave, which matters most on a shared or lab computer.

The menu is a `<details>` element, like the company switcher beside it: a native disclosure
widget that opens with the keyboard and works with no JavaScript at all.
"""

import secrets

import pytest
from originalentry.models import Assignment, Section, User, Variant, Workspace
from originalentry.packs import schema
from originalentry.packs.importer import import_content
from sqlalchemy import select

from tests.packs import testco_alpha

pytestmark = pytest.mark.db


@pytest.fixture
def people(session, client):
    pv = import_content(session, schema.load_pack(testco_alpha.PACK),
                        source_sha256=secrets.token_hex(32))
    variant_id = session.scalars(
        select(Variant.id).where(Variant.pack_version_id == pv.id)).first()
    section = Section(name="Sec", join_code=f"M{secrets.token_hex(3).upper()}")
    student = User(email=f"am-{secrets.token_hex(3)}@example.edu", role="student",
                   given_name="Ada", family_name="Sowande")
    instructor = User(email=f"ai-{secrets.token_hex(3)}@example.edu", role="instructor")
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
    return student, instructor, ws


def test_a_signed_out_visitor_is_offered_a_way_in(client):
    body = client.get("/").get_data(as_text=True)

    assert "Sign in" in body
    assert "Sign out" not in body


def test_a_student_can_sign_out_from_the_public_pages(client, people):
    student, _, _ = people
    client.sign_in(student)

    body = client.get("/").get_data(as_text=True)

    assert "Sign out" in body


def test_the_menu_lists_their_workspaces(client, people):
    student, _, ws = people
    client.sign_in(student)

    body = client.get("/").get_data(as_text=True)

    assert "TestCo Alpha" in body
    assert f"/w/{ws.public_id}/" in body


def test_a_student_can_sign_out_from_inside_their_books(client, people):
    """Where they actually are for the whole assignment, and where it was missing."""
    student, _, ws = people
    client.sign_in(student)

    body = client.get(f"/w/{ws.public_id}/testco-alpha/").get_data(as_text=True)

    assert "Sign out" in body


def test_signing_out_from_the_menu_actually_signs_them_out(client, people):
    student, _, ws = people
    client.sign_in(student)

    client.get("/auth/sign-out", follow_redirects=True)

    # Their books are no longer reachable without signing in again.
    assert client.get(f"/w/{ws.public_id}/testco-alpha/").status_code in (302, 401, 404)


def test_staff_get_the_menu_too(client, people):
    _, instructor, _ = people
    client.sign_in(instructor)

    body = client.get("/").get_data(as_text=True)

    assert "Sign out" in body


def test_the_menu_needs_no_javascript(client, people):
    """A disclosure widget the browser opens itself, like the company switcher beside it."""
    student, _, _ = people
    client.sign_in(student)

    body = client.get("/").get_data(as_text=True)

    assert "<details" in body
    assert "<summary" in body


def test_sign_out_sits_at_the_bottom_of_the_menu(client, people):
    """Below the workspaces, so the thing that ends the session is never the first target."""
    student, _, ws = people
    client.sign_in(student)

    body = client.get("/").get_data(as_text=True)

    assert body.index(f"/w/{ws.public_id}/") < body.index("/auth/sign-out")


# ── The menu says what it is before you open it ─────────────────────────────────────────

def test_the_closed_menu_carries_a_visible_title(client, people):
    """A trigger showing only someone's name does not read as a menu of their books."""
    student, _, _ = people
    client.sign_in(student)

    body = client.get("/").get_data(as_text=True)
    summary = body[body.index("<summary"):body.index("</summary>")]

    assert "Your workspaces" in summary


def test_staff_are_not_told_they_have_workspaces(client, people):
    """They have none, so the title has to say something else that is true."""
    _, instructor, _ = people
    client.sign_in(instructor)

    body = client.get("/").get_data(as_text=True)
    summary = body[body.index("<summary"):body.index("</summary>")]

    assert "Your workspaces" not in summary
    assert "Account" in summary


def test_the_open_menu_says_who_is_signed_in(client, people):
    """Identity moves inside, where it informs rather than disguising the trigger."""
    student, _, _ = people
    client.sign_in(student)

    body = client.get("/").get_data(as_text=True)

    assert student.email in body
