"""The save contract the browser talks to (T7.2, T7.4, S3.10, A26).

The protocol exists so that a student never loses an entry they have typed. Everything here works
without JavaScript as an ordinary form post; these tests pin what the page gets *in addition* when
the script is running: where to go next, when the work was saved, and the workspace version, so a
second tab can be told it is out of date.

The retrying itself is the script's job, but the property that makes retrying safe is the server's:
the same ``client_key`` twice is one entry, not two.
"""

from datetime import UTC, date, datetime, timedelta

import pytest
from parchment.models import Assignment, JournalEntry, Section, User, Variant, Workspace
from parchment.packs import schema
from parchment.packs.importer import import_content
from sqlalchemy import func, select

from tests.packs import testco_alpha

pytestmark = pytest.mark.db

SAVE_HEADER = {"X-Parchment-Save": "1"}


@pytest.fixture
def workspace(session, client):
    pack_version = import_content(session, schema.load_pack(testco_alpha.PACK),
                                  source_sha256="save" + "0" * 60)
    variant_id = session.scalars(
        select(Variant.id).where(Variant.pack_version_id == pack_version.id)
    ).first()
    section = Section(name="Sec", join_code="save-join")
    student = User(email="saver@example.edu", given_name="Ada", family_name="Nkemelu")
    session.add_all([section, student])
    session.flush()
    assignment = Assignment(section_id=section.id, title="December", company_policy="fixed",
                            fixed_pack_version_id=pack_version.id)
    session.add(assignment)
    session.flush()
    ws = Workspace(assignment_id=assignment.id, student_id=student.id,
                   pack_version_id=pack_version.id, variant_id=variant_id, status="in_progress")
    session.add(ws)
    session.flush()
    client.sign_in(student)
    return ws, student, assignment


def _url(workspace, suffix="/journals/general/entries/new"):
    return f"/w/{workspace.public_id}/testco-alpha{suffix}"


def _entry(client_key="typed-once", credit="1,200.00", **overrides):
    data = {
        "kind": "regular", "entry_date": "2026-12-02", "document_ref": "INV-1",
        "client_key": client_key, "workspace_version": "0",
        "line-1-account": "112", "line-1-party": "C-ONE", "line-1-debit": "1,200.00",
        "line-2-account": "401", "line-2-credit": credit,
    }
    data.update(overrides)
    return data


def _count(session, workspace):
    return session.execute(
        select(func.count()).select_from(JournalEntry).where(
            JournalEntry.workspace_id == workspace.id
        )
    ).scalar_one()


def test_the_form_arrives_with_a_key_the_browser_can_retry_on(client, workspace):
    ws, _, _ = workspace

    body = client.get(_url(ws)).get_data(as_text=True)

    assert 'name="client_key"' in body
    assert 'value=""' not in body.split('name="client_key"')[1][:40]  # it carries a value


def test_a_saved_entry_says_where_to_go_and_when_it_was_saved(client, workspace):
    ws, _, _ = workspace

    response = client.post(_url(ws), data=_entry(), headers=SAVE_HEADER)

    assert response.status_code == 200
    assert response.headers["X-Redirect-To"].endswith("/journals/general")
    assert response.headers["X-Saved-At"]
    assert int(response.headers["X-Workspace-Version"]) >= 1


def test_without_the_header_it_is_an_ordinary_form_post(client, workspace):
    ws, _, _ = workspace

    response = client.post(_url(ws), data=_entry())

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/journals/general")


def test_the_same_key_twice_is_one_entry(client, workspace, session):
    """What makes a retry safe: the browser may send the same save twice and often will."""
    ws, _, _ = workspace

    first = client.post(_url(ws), data=_entry(), headers=SAVE_HEADER)
    second = client.post(_url(ws), data=_entry(), headers=SAVE_HEADER)

    assert first.status_code == 200
    assert second.status_code == 200
    assert _count(session, ws) == 1


def test_a_refused_entry_comes_back_as_the_form_with_its_reasons(client, workspace, session):
    ws, _, _ = workspace

    response = client.post(_url(ws), data=_entry(credit="1,100.00"), headers=SAVE_HEADER)

    assert response.status_code == 422
    body = response.get_data(as_text=True)
    assert "out of balance by $100.00" in body
    assert 'value="1,100.00"' in body       # nothing the student typed is lost
    assert _count(session, ws) == 0


def test_a_workspace_that_has_moved_on_says_so(client, workspace, session):
    """Two tabs: the later write wins, and the other tab is told to reload (T7.5)."""
    ws, _, _ = workspace
    client.post(_url(ws), data=_entry(client_key="first"), headers=SAVE_HEADER)

    stale = client.post(_url(ws), data=_entry(client_key="second", workspace_version="0"),
                        headers=SAVE_HEADER)

    assert stale.status_code == 200
    assert stale.headers.get("X-Workspace-Stale") == "1"
    assert _count(session, ws) == 2      # the write still went through


def test_books_that_are_closed_refuse_the_save_and_say_where_to_look(client, workspace, session):
    ws, _, assignment = workspace
    assignment.due_at = datetime.now(UTC) - timedelta(hours=1)
    session.flush()

    response = client.post(_url(ws), data=_entry(), headers=SAVE_HEADER)

    assert response.status_code == 423
    assert response.headers["X-Redirect-To"]
    assert _count(session, ws) == 0


def test_a_signed_out_student_gets_401_rather_than_a_sign_in_page(client, workspace):
    """The script keeps the entry, sends them to sign in, and puts it back afterwards."""
    ws, _, _ = workspace
    client.get("/auth/sign-out")

    response = client.post(_url(ws), data=_entry(), headers=SAVE_HEADER)

    assert response.status_code == 401
    assert "/auth/sign-in" in response.headers["X-Redirect-To"]


def test_the_dates_and_lines_survive_a_refusal_for_any_reason(client, workspace):
    ws, _, _ = workspace

    response = client.post(
        _url(ws),
        data=_entry(**{"entry_date": "2027-01-04"}),  # outside the period
        headers=SAVE_HEADER,
    )

    assert response.status_code == 422
    body = response.get_data(as_text=True)
    assert "December 1–31" in body
    assert 'value="2027-01-04"' in body
    assert date(2027, 1, 4).isoformat() in body
