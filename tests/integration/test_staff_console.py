"""The staff console's first screens (I2.1–I2.5).

The console is small on purpose. These tests cover what it must never get wrong: a student cannot
reach it, and a row tells the instructor where each student is and what they were stuck on.
"""

import pytest
from parchment.models import Assignment, Section, User, Variant, Workspace
from parchment.packs import schema
from parchment.packs.importer import import_answer_keys, import_content
from parchment.services import workspace_write
from parchment.services.activity import record_refused_save
from parchment.services.dispositions import set_disposition
from sqlalchemy import select

from tests.packs import testco_alpha

pytestmark = pytest.mark.db


@pytest.fixture
def section(session):
    pv = import_content(session, schema.load_pack(testco_alpha.PACK), source_sha256="c" * 64)
    import_answer_keys(session, pv, {"A": schema.load_answer_key(testco_alpha.KEY_A)})
    variant = session.scalars(select(Variant).where(Variant.pack_version_id == pv.id)).first()
    sec = Section(name="ACCT 1010-02", join_code="staff-join")
    student = User(email="student@example.edu", given_name="Sam", family_name="Rivera")
    instructor = User(email="instructor@example.edu", role="instructor")
    session.add_all([sec, student, instructor])
    session.flush()
    assignment = Assignment(section_id=sec.id, title="December cycle", company_policy="fixed",
                            fixed_pack_version_id=pv.id)
    session.add(assignment)
    session.flush()
    ws = Workspace(assignment_id=assignment.id, student_id=student.id, pack_version_id=pv.id,
                   variant_id=variant.id, status="in_progress")
    session.add(ws)
    session.flush()
    return assignment, ws, student, instructor


def test_a_student_cannot_reach_the_console(client, section):
    assignment, _, student, _ = section
    client.sign_in(student)

    assert client.get("/staff/").status_code == 404
    assert client.get(f"/staff/progress/{assignment.public_id}").status_code == 404


def test_signed_out_visitors_are_sent_to_sign_in(client, section):
    response = client.get("/staff/")

    assert response.status_code == 302
    assert "/auth/sign-in" in response.headers["Location"]


def test_the_console_lists_the_assignments_and_their_sections(client, section):
    assignment, _, _, instructor = section
    client.sign_in(instructor)

    body = client.get("/staff/").get_data(as_text=True)

    assert "December cycle" in body
    assert "ACCT 1010-02" in body
    assert f"/staff/progress/{assignment.public_id}" in body


def test_progress_shows_where_a_student_is_and_what_they_were_stuck_on(client, section, session):
    assignment, ws, student, instructor = section
    workspace_write(session, ws.public_id, student, activity_kind="disposition",
                    mutate=lambda s, w: set_disposition(s, w, "INV-1", "record", None))
    record_refused_save(session, ws, document_ref="INV-2",
                        reason="This entry is out of balance by $140.00.")
    client.sign_in(instructor)

    body = client.get(f"/staff/progress/{assignment.public_id}").get_data(as_text=True)

    assert "Sam Rivera" in body
    assert "Documents" in body          # the stage reached
    assert "1 of 2" in body             # documents handled
    assert "INV-2" in body              # what the last refused save was about
    assert "out of balance" in body


def test_an_instructor_can_open_a_students_workspace_read_only(client, section):
    _, ws, _, instructor = section
    client.sign_in(instructor)

    body = client.get(f"/w/{ws.public_id}/testco-alpha/").get_data(as_text=True)

    assert "Sam Rivera" in body     # whose books these are
    assert "read-only" in body.lower()


def test_a_refused_save_in_the_browser_reaches_the_progress_screen(client, section, session):
    """I2.5 end to end: the student is refused, and the instructor sees what they were on."""
    assignment, ws, student, instructor = section
    client.sign_in(student)

    refused = client.post(
        f"/w/{ws.public_id}/testco-alpha/journals/general/entries/new",
        data={
            "kind": "regular", "entry_date": "2026-12-02", "document_ref": "INV-1",
            "line-1-account": "112", "line-1-party": "C-ONE", "line-1-debit": "1,200.00",
            "line-2-account": "401", "line-2-credit": "1,100.00",  # out of balance by $100
        },
    )
    assert refused.status_code == 422

    client.sign_in(instructor)
    body = client.get(f"/staff/progress/{assignment.public_id}").get_data(as_text=True)

    assert "INV-1" in body
    assert "out of balance by $100.00" in body
