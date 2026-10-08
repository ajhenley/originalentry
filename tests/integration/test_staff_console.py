"""The staff console's first screens (I2.1–I2.5).

The console is small on purpose. These tests cover what it must never get wrong: a student cannot
reach it, and a row tells the instructor where each student is and what they were stuck on.
"""

from datetime import UTC, datetime

import pytest
from originalentry.models import (
    ROLE_ADMIN,
    Assignment,
    PackVersion,
    Section,
    SectionStaff,
    User,
    Variant,
    Workspace,
)
from originalentry.packs import schema
from originalentry.packs.importer import import_answer_keys, import_content
from originalentry.services import workspace_write
from originalentry.services.activity import record_refused_save
from originalentry.services.dispositions import set_disposition
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
    # The instructor teaches this section. Without the row, scoped visibility (Task 4)
    # refuses them from their own class.
    session.add(SectionStaff(section_id=sec.id, user_id=instructor.id))
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


def test_an_instructor_sets_a_term_up_without_touching_the_database(client, section, session):
    """A13: a section, an assignment, a join code and an enrolled student, all through screens."""
    _, _, _, instructor = section
    client.sign_in(instructor)

    page = client.get("/staff/assignments/new").get_data(as_text=True)
    assert "TestCo Alpha" in page      # the catalogue offers the companies that are loaded

    created = client.post("/staff/assignments/new", data={
        "section_choice": "new",
        "section_name": "ACCT 1010-09",
        "section_term": "Fall 2026",
        "title": "December cycle",
        "pack_version_id": str(session.scalars(select(PackVersion.id)).first()),
        "mode": "paper",
        "due_at": "2026-12-18T23:59",
        "variant_policy": "round_robin",
    }, follow_redirects=True)

    body = created.get_data(as_text=True)
    assert created.status_code == 200
    assert "December cycle" in body
    assert "ACCT 1010-09" in body

    code = session.scalars(
        select(Section.join_code).where(Section.name == "ACCT 1010-09")
    ).one()
    assert code in body               # the instructor can read the code off the screen

    student = User(email="a13-student@example.edu", given_name="Nia", family_name="Bello")
    session.add(student)
    session.flush()
    client.sign_in(student)
    joined = client.post("/join", data={"code": code}, follow_redirects=True)

    assert joined.status_code == 200
    assert "December cycle" in joined.get_data(as_text=True)


def test_a_code_that_is_not_in_use_says_so_without_saying_more(client, section, session):
    _, _, student, _ = section
    client.sign_in(student)

    body = client.post("/join", data={"code": "NOTACODE"},
                       follow_redirects=True).get_data(as_text=True)

    assert "not in use" in body


def test_cloning_an_assignment_moves_its_dates(client, section, session):
    assignment, _, _, instructor = section
    assignment.due_at = datetime(2026, 12, 18, 23, 59, tzinfo=UTC)
    session.flush()
    client.sign_in(instructor)

    response = client.post(f"/staff/assignments/{assignment.public_id}/clone",
                           data={"shift_days": "120"}, follow_redirects=True)

    assert response.status_code == 200
    clones = session.scalars(
        select(Assignment).where(Assignment.cloned_from_id == assignment.id)
    ).all()
    assert len(clones) == 1
    assert clones[0].due_at.date().isoformat() == "2027-04-17"


def test_the_catalogue_lists_the_companies_and_takes_an_upload(client, section, session):
    """I1.7, I1.10: what the app holds, and a way to add to it that validates first."""
    import io
    import json
    import zipfile

    from tests.packs import testco_alpha

    _, _, _, instructor = section
    # Loading a pack is cohort-wide, so the screen is admin-only (Task 4).
    instructor.role = ROLE_ADMIN
    session.flush()
    client.sign_in(instructor)

    body = client.get("/staff/catalogue").get_data(as_text=True)
    assert "TestCo Alpha" in body
    assert "Upload a pack" in body

    second = dict(testco_alpha.PACK, version=2)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("pack.json", json.dumps(second))
        archive.writestr("answer_keys/A.json", json.dumps(testco_alpha.KEY_A))
    buffer.seek(0)

    uploaded = client.post("/staff/catalogue", follow_redirects=True,
                           data={"pack": (buffer, "testco-alpha-v2.zip")},
                           content_type="multipart/form-data")

    assert uploaded.status_code == 200
    assert "version 2" in uploaded.get_data(as_text=True).lower()


def test_a_pack_that_fails_validation_is_refused_with_its_problems(client, section, session):
    import io
    import json
    import zipfile

    from tests.packs import testco_alpha

    _, _, _, instructor = section
    # Loading a pack is cohort-wide, so the screen is admin-only (Task 4).
    instructor.role = ROLE_ADMIN
    session.flush()
    client.sign_in(instructor)

    broken = json.loads(json.dumps(testco_alpha.PACK))
    broken["version"] = 5
    for account in broken["accounts"]:
        if "income_summary" in account.get("roles", []):
            account["roles"] = []
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("pack.json", json.dumps(broken))
    buffer.seek(0)

    response = client.post("/staff/catalogue", data={"pack": (buffer, "broken.zip")},
                           content_type="multipart/form-data")

    assert response.status_code == 422
    body = response.get_data(as_text=True)
    assert "income_summary" in body
    assert "V5" in body


def test_staff_landing_on_the_student_home_are_sent_to_their_console(client, section):
    """An instructor has no books of their own; telling them to find a join code is no help."""
    _, _, _, instructor = section
    client.sign_in(instructor)

    response = client.get("/home")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/staff/")


def test_a_student_with_no_workspaces_is_offered_the_way_in(client, section, session):
    newcomer = User(email="newcomer@example.edu", given_name="Ada", family_name="Nkemelu")
    session.add(newcomer)
    session.flush()
    client.sign_in(newcomer)

    body = client.get("/home").get_data(as_text=True)

    assert "/join" in body            # the empty screen is an invitation to act
    assert "join code" in body.lower()
