"""Getting from a document to its entry, with the document's own date (S3.3).

Two faults reported from one screen. Entries showed Dec 1 when their documents were Dec 10 and
Dec 15, because the date field defaults to the start of the period whatever you are recording.
And "Record an entry" on a document marks the decision and then leaves you to find your own way
to a journal, where the document has to be picked out of a list again.

Both come from the same place: the entry form never knew which document it was for.

The journal is still the student's to choose. It is marked, so the document page offers all of
them rather than guessing.
"""

import re
import secrets

import pytest
from originalentry.models import Assignment, Section, SourceDocument, User, Variant, Workspace
from originalentry.packs import schema
from originalentry.packs.importer import import_content
from sqlalchemy import select

from tests.packs import testco_alpha

pytestmark = pytest.mark.db


@pytest.fixture
def workspace(session, client):
    pv = import_content(session, schema.load_pack(testco_alpha.PACK),
                        source_sha256=secrets.token_hex(32))
    variant_id = session.scalars(
        select(Variant.id).where(Variant.pack_version_id == pv.id)).first()
    section = Section(name="Sec", join_code=f"E{secrets.token_hex(3).upper()}")
    student = User(email=f"ed-{secrets.token_hex(3)}@example.edu", role="student")
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
    doc = session.scalars(
        select(SourceDocument).where(SourceDocument.pack_version_id == pv.id,
                                     SourceDocument.ref == "INV-2")).one()
    session.commit()
    return ws, student, doc


def _form(client, ws, query=""):
    return client.get(
        f"/w/{ws.public_id}/testco-alpha/journals/general/entries/new{query}"
    ).get_data(as_text=True)


def _date_value(html: str) -> str:
    return re.search(r'name="entry_date"[^>]*value="([^"]*)"', html).group(1)


def test_without_a_document_the_date_still_defaults_to_the_period(client, workspace):
    ws, student, _ = workspace
    client.sign_in(student)

    assert _date_value(_form(client, ws)) == "2026-12-01"


def test_a_document_brings_its_own_date(client, workspace):
    """The reported fault: an entry for a document dated the tenth arrived dated the first."""
    ws, student, doc = workspace
    client.sign_in(student)

    html = _form(client, ws, f"?document={doc.ref}")

    assert _date_value(html) == doc.doc_date.isoformat()
    assert doc.doc_date.isoformat() != "2026-12-01", "the fixture must not sit on the start"


def test_the_document_arrives_already_chosen(client, workspace):
    ws, student, doc = workspace
    client.sign_in(student)

    html = _form(client, ws, f"?document={doc.ref}")
    chosen = re.search(rf'<option value="{doc.ref}"[^>]*selected', html)

    assert chosen is not None


def test_a_document_that_is_not_this_company_s_is_ignored(client, workspace):
    ws, student, _ = workspace
    client.sign_in(student)

    html = _form(client, ws, "?document=NOT-A-DOCUMENT")

    assert _date_value(html) == "2026-12-01"


def test_the_document_page_offers_a_way_into_each_journal(client, workspace):
    """Which journal is the student's judgement and it is marked, so all of them are offered."""
    ws, student, doc = workspace
    client.sign_in(student)
    page = client.get(f"/w/{ws.public_id}/testco-alpha/documents/{doc.ref}").get_data(as_text=True)
    csrf = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', page).group(1)
    client.post(f"/w/{ws.public_id}/testco-alpha/documents/{doc.ref}/disposition",
                data={"csrf_token": csrf, "choice": "record"}, follow_redirects=True)

    body = client.get(
        f"/w/{ws.public_id}/testco-alpha/documents/{doc.ref}").get_data(as_text=True)

    assert f"/journals/general/entries/new?document={doc.ref}" in body
    assert f"/journals/sales/entries/new?document={doc.ref}" in body
