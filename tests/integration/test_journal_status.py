"""What the journal says about an entry, and what it lets you do with it (S3.7).

Two complaints from one screen. The status read "Not posted · sub posted", which is accurate and
says two different things in two different vocabularies. And the Actions cell was simply empty
for that entry while its neighbour offered Void, with nothing to say why.

Void disappears once an entry has been posted anywhere, which is right: the posting is what the
ledgers were built from, and it has to be reversed before the entry can go. What was missing was
saying so.
"""

import re
import secrets
from datetime import date

import pytest
from originalentry.forms.entries import EntryCommand, LineCommand
from originalentry.models import Assignment, Section, User, Variant, Workspace
from originalentry.packs import schema
from originalentry.packs.importer import import_content
from originalentry.services import workspace_write
from originalentry.services.entries import record_entry
from originalentry.services.posting import post_entry_subsidiary
from sqlalchemy import select

from tests.packs import testco_alpha

pytestmark = pytest.mark.db


@pytest.fixture
def workspace(session, client):
    pv = import_content(session, schema.load_pack(testco_alpha.PACK),
                        source_sha256=secrets.token_hex(32))
    variant_id = session.scalars(
        select(Variant.id).where(Variant.pack_version_id == pv.id)).first()
    section = Section(name="Sec", join_code=f"S{secrets.token_hex(3).upper()}")
    student = User(email=f"js-{secrets.token_hex(3)}@example.edu", role="student")
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
    return ws, student


def _record(session, ws, student, key="js-1"):
    command = EntryCommand(
        journal_key="general", kind="regular", document_ref="INV-1",
        entry_date=date(2026, 12, 2), description=None,
        lines=[LineCommand("112", "C-ONE", 120000, 0), LineCommand("401", None, 0, 120000)],
        client_key=key,
    )
    return workspace_write(session, ws.public_id, student, activity_kind="save",
                           mutate=lambda s, w: record_entry(s, w, command))


def _row(client, ws) -> str:
    body = client.get(
        f"/w/{ws.public_id}/testco-alpha/journals/general").get_data(as_text=True)
    start = body.index("<tbody")
    return body[start:body.index("</tbody>", start)]


def test_an_unposted_entry_offers_void(client, session, workspace):
    ws, student = workspace
    _record(session, ws, student)
    session.commit()
    client.sign_in(student)

    assert "Void" in _row(client, ws)


def test_the_status_reads_in_plain_words(client, session, workspace):
    """"Not posted · sub posted" says two things in two vocabularies."""
    ws, student = workspace
    _record(session, ws, student)
    session.commit()
    client.sign_in(student)

    row = _row(client, ws)

    assert "sub posted" not in row
    assert "sub open" not in row
    assert "subsidiary ledger" in row.lower()


def test_a_posted_entry_says_why_it_cannot_be_voided(client, session, workspace):
    """The Actions cell went blank with no explanation and no way forward."""
    ws, student = workspace
    entry = _record(session, ws, student)
    workspace_write(session, ws.public_id, student, activity_kind="post",
                    mutate=lambda s, w: post_entry_subsidiary(s, w, entry.public_id))
    session.commit()
    client.sign_in(student)

    row = _row(client, ws)

    assert "Void" not in row                       # still refused, which is right
    assert "reverse" in row.lower()                # and it says what to do instead


def test_a_posted_entry_still_says_where_it_reached(client, session, workspace):
    ws, student = workspace
    entry = _record(session, ws, student)
    workspace_write(session, ws.public_id, student, activity_kind="post",
                    mutate=lambda s, w: post_entry_subsidiary(s, w, entry.public_id))
    session.commit()
    client.sign_in(student)

    row = re.sub(r"\s+", " ", _row(client, ws))

    assert "subsidiary ledger" in row.lower()
    assert "general ledger" in row.lower()
