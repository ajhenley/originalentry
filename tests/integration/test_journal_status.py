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
from originalentry.services.posting import post_entry_subsidiary, post_journal_general
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


def _record(session, ws, student, key="js-1", *, party="C-ONE", document="INV-1"):
    command = EntryCommand(
        journal_key="general", kind="regular", document_ref=document,
        entry_date=date(2026, 12, 2), description=None,
        lines=[LineCommand("112", party, 120000, 0), LineCommand("401", None, 0, 120000)],
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


# ── A posting you can actually look at ──────────────────────────────────────────────────
#
# The Postings list said "Subsidiary posting 1" and offered to reverse it. It did not say when it
# happened, how much it covered, or where the result could be seen. Reversing was the only thing
# you could do with it, which is a strange only option for something you cannot inspect.

def test_a_posting_says_when_it_happened_and_how_much_it_covered(client, session, workspace):
    ws, student = workspace
    entry = _record(session, ws, student)
    workspace_write(session, ws.public_id, student, activity_kind="post",
                    mutate=lambda s, w: post_entry_subsidiary(s, w, entry.public_id))
    session.commit()
    client.sign_in(student)

    body = client.get(f"/w/{ws.public_id}/testco-alpha/journals/general").get_data(as_text=True)
    postings = body[body.index("Postings"):]

    assert "1 entry" in postings
    assert re.search(r"\d{1,2} \w{3}", postings), "no date on the posting"


def test_a_subsidiary_posting_links_to_the_ledger_it_reached(client, session, workspace):
    ws, student = workspace
    entry = _record(session, ws, student)
    workspace_write(session, ws.public_id, student, activity_kind="post",
                    mutate=lambda s, w: post_entry_subsidiary(s, w, entry.public_id))
    session.commit()
    client.sign_in(student)

    body = client.get(f"/w/{ws.public_id}/testco-alpha/journals/general").get_data(as_text=True)
    postings = body[body.index("Postings"):]

    assert f"/w/{ws.public_id}/testco-alpha/ledgers/customer" in postings


def test_a_general_posting_links_to_the_general_ledger(client, session, workspace):
    ws, student = workspace
    _record(session, ws, student)
    session.commit()
    client.sign_in(student)
    page = client.get(f"/w/{ws.public_id}/testco-alpha/journals/general").get_data(as_text=True)
    csrf = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', page).group(1)
    client.post(f"/w/{ws.public_id}/testco-alpha/journals/general/post",
                data={"csrf_token": csrf}, follow_redirects=True)

    body = client.get(f"/w/{ws.public_id}/testco-alpha/journals/general").get_data(as_text=True)
    postings = body[body.index("Postings"):]

    assert f"/w/{ws.public_id}/testco-alpha/ledgers/general" in postings


# ── Telling one posting from another ────────────────────────────────────────────────────
#
# "Subsidiary posting 1", "Subsidiary posting 2", each with a Reverse button. An ordinal is a
# serial number, not a description: with several of them there is nothing to choose between them,
# and reversing is destructive. A posting is a set of entries, so it should name them, using the
# same references the table above prints.

def _postings(client, ws) -> str:
    body = client.get(f"/w/{ws.public_id}/testco-alpha/journals/general").get_data(as_text=True)
    return re.sub(r"\s+", " ", body[body.index("Postings"):])


def test_a_posting_names_the_entries_it_covered(client, session, workspace):
    ws, student = workspace
    first = _record(session, ws, student, key="js-1")
    _record(session, ws, student, key="js-2", party="C-TWO", document="INV-2")
    workspace_write(session, ws.public_id, student, activity_kind="post",
                    mutate=lambda s, w: post_entry_subsidiary(s, w, first.public_id))
    session.commit()
    client.sign_in(student)

    postings = _postings(client, ws)

    assert "J1" in postings
    assert "J2" not in postings       # the entry this posting left alone


def test_a_posting_of_several_entries_names_them_all(client, session, workspace):
    """Posting a journal to the general ledger takes every live entry in one run, so the run has
    to list them rather than say "2 entries" and leave you to work out which two."""
    ws, student = workspace
    _record(session, ws, student, key="js-1")
    _record(session, ws, student, key="js-2", party="C-TWO", document="INV-2")
    workspace_write(session, ws.public_id, student, activity_kind="post",
                    mutate=lambda s, w: post_journal_general(s, w, "general"))
    session.commit()
    client.sign_in(student)

    postings = _postings(client, ws)
    first_run = postings[:postings.index("</li>")]

    assert "J1, J2" in first_run


def test_a_subsidiary_posting_names_whose_accounts_it_reached(client, session, workspace):
    """Which customer was charged is the thing a student is checking when something looks wrong
    in the customers ledger, and it is what tells two postings apart at a glance."""
    ws, student = workspace
    entry = _record(session, ws, student)
    workspace_write(session, ws.public_id, student, activity_kind="post",
                    mutate=lambda s, w: post_entry_subsidiary(s, w, entry.public_id))
    session.commit()
    client.sign_in(student)

    postings = _postings(client, ws)

    assert "Firstborn Supply" in postings


def test_the_reverse_button_says_which_posting_it_would_undo(client, session, workspace):
    """Two identical "Reverse" buttons one above the other, read out by a screen reader or
    glanced at in a hurry, are the same button twice."""
    ws, student = workspace
    entry = _record(session, ws, student)
    workspace_write(session, ws.public_id, student, activity_kind="post",
                    mutate=lambda s, w: post_entry_subsidiary(s, w, entry.public_id))
    session.commit()
    client.sign_in(student)

    postings = _postings(client, ws)

    assert 'aria-label="Reverse the posting of J1"' in postings
