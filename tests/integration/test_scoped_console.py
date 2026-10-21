"""The ordinary cases a matrix cannot express.

tests/guards/test_scoping.py walks every route and asks only whether it refused or admitted.
These are the few things that have to be true in words: a co-teacher is a teacher, a teacher can
still open their own students' books, the lists are narrowed rather than refused, and a teacher
attached to nothing is told so rather than shown an empty screen.
"""

from datetime import UTC, datetime

import pytest
from markupsafe import escape
from originalentry import messages
from originalentry.extensions import db
from originalentry.models import Assignment, SectionStaff
from originalentry.services.assignments import create_section

from tests.scoping_world import (
    foreign_world,
    own_section_world,
    staff_account,
    worked_world,
)

pytestmark = pytest.mark.db


@pytest.fixture
def owner(session):
    return staff_account(session, "console-owner@example.edu", name="Ada")


@pytest.fixture
def outsider(session):
    """A teacher attached to no section at all. Brand new, because Task 2's backfill attached
    every existing section to every staff member who existed when it ran."""
    return staff_account(session, "console-outsider@example.edu", name="Noa")


@pytest.fixture
def second_teacher(session):
    return staff_account(session, "console-co-teacher@example.edu", name="Kit")


@pytest.fixture
def worked(session, owner):
    return worked_world(session, owner)


@pytest.fixture
def mine(session, owner):
    return own_section_world(session, owner)


@pytest.fixture
def foreign(session):
    return foreign_world(session)


def test_a_co_teacher_sees_the_same_marks(client, session, owner, second_teacher, worked):
    """Two rows in section_staff, one section, the same view of it."""
    session.add(SectionStaff(section_id=worked["section_id"], user_id=second_teacher.id))
    session.commit()
    client.sign_in(second_teacher)
    assert client.get(f"/staff/grading/{worked['assignment']}").status_code == 200


def test_a_teacher_can_still_open_their_own_students_books(client, owner, worked):
    """workspace_view deliberately opens a student's books to staff, with a banner naming whose
    they are (I2.4). Scoping must not break marking in the name of securing it."""
    client.sign_in(owner)
    response = client.get(f"/w/{worked['workspace']}/{worked['company_slug']}/journals")

    assert response.status_code == 200
    # The real copy, from the one place it is written, escaped the way Jinja renders it.
    banner = str(escape(messages.viewing_students_books(worked["student_name"])))
    assert banner in response.get_data(as_text=True)


def test_a_teacher_with_no_sections_is_told_so(client, outsider):
    """Review Focus 3. An empty dashboard and no explanation reads as an outage."""
    client.sign_in(outsider)
    page = client.get("/staff/").get_data(as_text=True)
    assert "You are teaching no sections yet." in page


def test_the_assignment_list_shows_only_your_own_sections(client, owner, mine, foreign):
    """staff.index has no id in its path, so it is scoped by what the query returns."""
    client.sign_in(owner)
    page = client.get("/staff/").get_data(as_text=True)

    assert mine["title"] in page
    assert foreign["title"] not in page, "the dashboard listed a colleague's assignment"


def test_with_the_switch_off_the_list_shows_a_colleagues_section_again(
        monkeypatch, app, client, owner, mine, foreign):
    """The other state of the kill switch, for the half a route walk cannot see.

    tests/guards/test_scoping.py inverts the refusal matrix with the switch off, but every list
    query is EXEMPT there -- it is scoped by what the query returns, not by refusing the request.
    So this is the only thing that would catch a list that narrows regardless of the flag, which
    is the half of the switch no route-level guard would notice.

    ``monkeypatch.setitem``, never assignment: ``app`` is session-scoped and a leaked False would
    disable the guard for every test that ran afterwards.
    """
    monkeypatch.setitem(app.config, "SCOPED_VISIBILITY", False)
    client.sign_in(owner)
    page = client.get("/staff/").get_data(as_text=True)

    assert mine["title"] in page
    assert foreign["title"] in page, "the switch is off and the list was still narrowed"


def test_the_section_dropdown_offers_only_your_own(client, owner, mine, foreign):
    """The new-assignment form, where a section you do not teach must not even be offered -- nor
    named in the prerequisite list beside it, which is a colleague's section and title."""
    client.sign_in(owner)
    page = client.get("/staff/assignments/new").get_data(as_text=True)

    assert f'value="{mine["section_id"]}"' in page
    assert f'value="{foreign["section_id"]}"' not in page
    # Both spellings, because the name holds an apostrophe and Jinja escapes it on the way out:
    # asserting only the raw form would pass on a page that had leaked the escaped one.
    assert foreign["section_name"] not in page
    assert str(escape(foreign["section_name"])) not in page


def test_a_crafted_create_naming_another_teachers_section_is_refused(client, owner, foreign):
    """Filtering the dropdown is not a permission check."""
    client.sign_in(owner)
    response = client.post("/staff/assignments/new", data={
        "title": "Not mine", "company_policy": "fixed",
        "pack_version_id": str(foreign["pack_version_id"]),
        "section_choice": "existing", "section_id": str(foreign["section_id"]),
    })
    assert response.status_code == 422
    assert "not one you teach" in response.get_data(as_text=True)


def test_a_crafted_prerequisite_naming_another_teachers_assignment_is_dropped(
        client, session, owner, mine, foreign):
    """The prerequisite dropdown is filtered, which is not a permission check either.

    A crafted POST would otherwise make this teacher's assignment wait on one in a section they
    do not teach -- a colleague's assignment, named in a gate their students will meet. An id you
    were never offered reads as absent rather than as an error, so the assignment is created and
    the prerequisite is simply not set.
    """
    client.sign_in(owner)
    response = client.post("/staff/assignments/new", data={
        "title": "Mine, with a borrowed gate", "company_policy": "fixed",
        "pack_version_id": str(mine["pack_version_id"]),
        "section_choice": "existing", "section_id": str(mine["section_id"]),
        "prerequisite": foreign["assignment"],
        "mode": "screen", "variant_policy": "round_robin", "late_policy": "closed",
    })

    assert response.status_code == 302, response.get_data(as_text=True)[:400]
    made = session.scalars(db.select(Assignment).filter_by(
        title="Mine, with a borrowed gate")).one()
    assert made.prerequisite_assignment_id is None, (
        "a crafted POST set a prerequisite in a section this teacher does not teach")


def test_the_marks_csv_and_the_diagnostics_export_are_scoped(client, outsider, foreign):
    """The two routes that hand student data out in bulk."""
    client.sign_in(outsider)
    for path in (f"/staff/grading/{foreign['assignment']}/marks.csv",
                 f"/staff/diagnostics/{foreign['assignment']}/export.csv"):
        assert client.get(path).status_code == 404, path


def test_the_teacher_who_makes_a_section_can_still_use_it(client, session, owner):
    """The create-and-be-refused trap: a teacher makes an assignment with a NEW section and must
    be able to open the thing they just made. create_section attaches them (Task 2); this is the
    end-to-end proof that the two halves meet."""
    section = create_section(session, name="Brand new", term="Spring", actor=owner)
    session.commit()
    client.sign_in(owner)
    assert client.get(f"/staff/sections/{section.id}/availability").status_code == 200


#: The upload form's own id. Asserted on instead of the words "Upload a pack", which also appear
#: in the empty-catalogue sentence -- so the old assertion passed only because the production
#: database always had packs in it, and failed the first time the suite ran against an empty
#: development branch. A control is a control; prose is prose.
UPLOAD_CONTROL = 'id="pack"'


def test_the_catalogue_upload_is_admin_only(client, session, owner):
    """Cohort-wide, so admin-only -- and the control is hidden rather than left to 404."""
    client.sign_in(owner)
    page = client.get("/staff/catalogue").get_data(as_text=True)
    assert UPLOAD_CONTROL not in page
    assert "/staff/catalogue" in page, "the page did not render at all"

    refused = client.post("/staff/catalogue", data={})
    assert refused.status_code == 404

    owner.role = "admin"
    session.commit()
    client.sign_in(owner)
    assert UPLOAD_CONTROL in client.get("/staff/catalogue").get_data(as_text=True)


def test_a_teacher_is_never_told_to_upload_a_pack(client, session, owner):
    """It used to be. The empty-state sentence said "Upload a pack the generator made" to
    everybody, which is an instruction a teacher cannot follow -- the control is admin-only and
    the POST 404s. Found by running the suite against an empty database for the first time.

    This half holds whatever the catalogue contains, so it runs against the real page.
    """
    client.sign_in(owner)

    page = client.get("/staff/catalogue").get_data(as_text=True)

    assert UPLOAD_CONTROL not in page
    assert "Upload a pack" not in page, "told a teacher to do something only an admin can do"


def test_an_empty_catalogue_tells_a_teacher_who_can_add_one(client, session, owner, monkeypatch):
    """The other half, which needs the catalogue to be *empty*.

    It used to read that from the database, which made it a test of whether anybody had imported
    anything -- it passed on a fresh branch and failed the moment a chapter pack was imported into
    the shared development database, and it would fail in production for the same reason. The
    empty state is a property of the view and the template, so the catalogue is emptied here
    instead of hoping the database is.
    """
    from originalentry.staff import views as staff_views

    monkeypatch.setattr(staff_views, "_catalogue_rows", lambda: [])
    client.sign_in(owner)

    page = client.get("/staff/catalogue").get_data(as_text=True)

    assert "The catalogue is empty" in page, "the empty state did not render"
    assert "administrator" in page.lower(), "did not say who can add one"
    assert "Upload a pack" not in page, "told a teacher to do something only an admin can do"


def test_an_archived_section_of_yours_is_still_yours(client, session, owner):
    """_my_sections filters archived sections out of the dropdown; may_see_section does not care
    about archiving, and the availability screen for one must stay reachable."""
    section = create_section(session, name="Last term", term="Autumn", actor=owner)
    section.archived_at = datetime.now(UTC)
    session.commit()
    client.sign_in(owner)
    assert client.get(f"/staff/sections/{section.id}/availability").status_code == 200


def test_a_section_nobody_teaches_is_invisible_to_a_teacher(client, session, owner):
    """The CLI and the fixtures create sections with no actor, so a section with no staff row is
    a real state. It belongs to nobody, which means it is not everybody's."""
    orphan = create_section(session, name="Imported, unattached", term="Spring", actor=None)
    session.commit()
    assert session.scalars(
        db.select(SectionStaff).filter_by(section_id=orphan.id)).all() == []

    client.sign_in(owner)
    assert client.get(f"/staff/sections/{orphan.id}/availability").status_code == 404


def test_an_admin_sees_every_section_in_the_dropdown(client, session, foreign):
    """The admin exemption, where it is a query rather than a check."""
    admin = staff_account(session, "console-admin@example.edu", role="admin", name="Rae")
    client.sign_in(admin)
    page = client.get("/staff/assignments/new").get_data(as_text=True)
    assert f'value="{foreign["section_id"]}"' in page


def test_the_switch_off_says_so_in_the_console(monkeypatch, client, app, owner):
    """A supported state in which the privacy control is absent must not be a quiet one.

    monkeypatch.setitem rather than assign-and-restore: ``app`` is session-scoped, and a flag left
    False by a failing assertion would disable the guard for every later test in the run.
    """
    client.sign_in(owner)
    assert "Scoped visibility is off" not in client.get("/staff/").get_data(as_text=True)

    monkeypatch.setitem(app.config, "SCOPED_VISIBILITY", False)
    assert "Scoped visibility is off" in client.get("/staff/").get_data(as_text=True)
