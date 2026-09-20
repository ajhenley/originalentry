"""Importing a roster from CSV (I1.5).

The join code is the ordinary way in. A roster is for the first day of term, when an instructor
has the registrar's export and forty students who have not been told anything yet.

Importing an address does not make it anyone's account: sign-in is still a link sent to that
address, so an imported row is an enrolment waiting for the person who can read the mail. That is
why the import is safe to hand an instructor at all.
"""

import io
import secrets

import pytest
from originalentry.models import Enrollment, Section, User, Workspace
from originalentry.packs import schema
from originalentry.packs.importer import import_content
from originalentry.services.assignments import create_assignment
from originalentry.services.roster import RosterRefused, import_roster
from sqlalchemy import func, select

from tests.packs import testco_alpha

pytestmark = pytest.mark.db

ROSTER = """email,given name,family name
ada@example.edu,Ada,Sowande
ola@example.edu,Ola,Bello
sam@example.edu,Sam,Rivera
"""


@pytest.fixture
def section(session, client):
    pv = import_content(session, schema.load_pack(testco_alpha.PACK),
                        source_sha256=secrets.token_hex(32))
    sec = Section(name="ACCT 1010", join_code=f"R{secrets.token_hex(3).upper()}")
    instructor = User(email=f"ri-{secrets.token_hex(3)}@example.edu", role="instructor")
    session.add_all([sec, instructor])
    session.flush()
    create_assignment(session, section=sec, title="December", pack_version=pv)
    return sec, instructor


def _enrolled(session, sec):
    return session.scalars(
        select(User.email).join(Enrollment, Enrollment.user_id == User.id)
        .where(Enrollment.section_id == sec.id).order_by(User.email)
    ).all()


def test_a_roster_enrols_every_student(session, section):
    sec, instructor = section

    report = import_roster(session, section=sec, csv_text=ROSTER, actor=instructor)

    assert report.enrolled == 3
    assert _enrolled(session, sec) == ["ada@example.edu", "ola@example.edu", "sam@example.edu"]


def test_it_opens_their_books(session, section):
    """Enrolled but with nothing to open is not enrolled, as far as a student can tell."""
    sec, instructor = section

    import_roster(session, section=sec, csv_text=ROSTER, actor=instructor)

    opened = session.execute(
        select(func.count()).select_from(Workspace)
        .join(User, Workspace.student_id == User.id)
        .join(Enrollment, Enrollment.user_id == User.id)
        .where(Enrollment.section_id == sec.id)
    ).scalar_one()
    assert opened == 3


def test_running_it_again_changes_nothing(session, section):
    """An instructor who is not sure whether the first one worked will run it again."""
    sec, instructor = section
    import_roster(session, section=sec, csv_text=ROSTER, actor=instructor)

    report = import_roster(session, section=sec, csv_text=ROSTER, actor=instructor)

    assert report.enrolled == 0
    assert report.already == 3
    assert len(_enrolled(session, sec)) == 3


def test_it_keeps_the_name_an_existing_student_already_gave(session, section):
    """The registrar's spelling does not get to overwrite what someone called themselves."""
    sec, instructor = section
    session.add(User(email="ada@example.edu", given_name="Ada", family_name="Sowande-Cole"))
    session.flush()

    import_roster(session, section=sec, csv_text=ROSTER, actor=instructor)

    ada = session.scalars(select(User).where(User.email == "ada@example.edu")).one()
    assert ada.family_name == "Sowande-Cole"


def test_an_imported_row_is_marked_as_coming_from_the_roster(session, section):
    sec, instructor = section

    import_roster(session, section=sec, csv_text=ROSTER, actor=instructor)

    sources = set(session.scalars(
        select(Enrollment.source).where(Enrollment.section_id == sec.id)
    ))
    assert sources == {"roster"}


def test_a_row_with_no_usable_address_is_reported_by_line(session, section):
    sec, instructor = section
    text = "email,given name,family name\nada@example.edu,Ada,Sowande\nnot-an-address,Ola,Bello\n"

    report = import_roster(session, section=sec, csv_text=text, actor=instructor)

    assert report.enrolled == 1                       # the good row still goes in
    assert [line for line, _ in report.refused] == [3]  # counting the header, as a spreadsheet does


def test_a_file_with_no_email_column_is_refused_whole(session, section):
    sec, instructor = section

    with pytest.raises(RosterRefused):
        import_roster(session, section=sec, csv_text="name,id\nAda,1\n", actor=instructor)

    assert _enrolled(session, sec) == []


def test_it_will_not_quietly_make_a_student_of_a_member_of_staff(session, section):
    sec, instructor = section
    text = f"email,given name,family name\n{instructor.email},Dana,Okonjo\n"

    report = import_roster(session, section=sec, csv_text=text, actor=instructor)

    assert report.enrolled == 0
    assert len(report.refused) == 1
    assert instructor.role == "instructor"


def test_the_section_screen_offers_the_import(client, session, section):
    sec, instructor = section
    session.commit()
    client.sign_in(instructor)

    body = client.get(f"/staff/sections/{sec.id}/availability").get_data(as_text=True)

    assert f"/staff/sections/{sec.id}/roster" in body
    assert "multipart/form-data" in body


def test_an_instructor_uploads_the_file(client, session, section):
    sec, instructor = section
    session.commit()
    client.sign_in(instructor)

    response = client.post(
        f"/staff/sections/{sec.id}/roster",
        data={"roster": (io.BytesIO(ROSTER.encode()), "roster.csv")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert len(_enrolled(session, sec)) == 3
