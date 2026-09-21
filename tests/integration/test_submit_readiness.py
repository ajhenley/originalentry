"""What the hand-in page tells you before you hand in (S6.4).

Written against a real set of books. A student recorded 28 entries across five journals, fixed
two of them on appeal, handed in twice, and scored 73. Of the 26.5 marks missing, 23 came from
one thing: not one entry had been posted to the general ledger. Subsidiary agreement scored
zero for the same reason, because a control account with no balance cannot agree with anything.

The hand-in page counted documents handled, entries recorded and statements started, and its
own prose told them to check they had "recorded and posted" their entries. It never counted the
posting. The one number that decided a quarter of the mark was the one number not on the page.

It warns rather than refuses: handing in unfinished work is the student's decision to make.
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
from originalentry.services.entries import record_entry, void_entry
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
    section = Section(name="Sec", join_code=f"R{secrets.token_hex(3).upper()}")
    student = User(email=f"sr-{secrets.token_hex(3)}@example.edu", role="student")
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


def _record(session, ws, student, key="sr-1", *, party="C-ONE", document="INV-1"):
    command = EntryCommand(
        journal_key="general", kind="regular", document_ref=document,
        entry_date=date(2026, 12, 2), description=None,
        lines=[LineCommand("112", party, 120000, 0), LineCommand("401", None, 0, 120000)],
        client_key=key,
    )
    return workspace_write(session, ws.public_id, student, activity_kind="save",
                           mutate=lambda s, w: record_entry(s, w, command))


def _page(client, ws) -> str:
    body = client.get(f"/w/{ws.public_id}/testco-alpha/submit").get_data(as_text=True)
    return re.sub(r"\s+", " ", body)


def test_it_says_which_journal_has_entries_not_posted(client, session, workspace):
    """The whole point: name the journal, so there is somewhere to go."""
    ws, student = workspace
    _record(session, ws, student)
    session.commit()
    client.sign_in(student)

    page = _page(client, ws)

    assert "General Journal" in page


def test_it_links_to_the_journal_that_needs_posting(client, session, workspace):
    ws, student = workspace
    _record(session, ws, student)
    session.commit()
    client.sign_in(student)

    page = _page(client, ws)

    assert f"/w/{ws.public_id}/testco-alpha/journals/general" in page


def test_a_journal_with_everything_posted_is_not_listed(client, session, workspace):
    ws, student = workspace
    entry = _record(session, ws, student)
    workspace_write(session, ws.public_id, student, activity_kind="post",
                    mutate=lambda s, w: post_journal_general(s, w, "general"))
    workspace_write(session, ws.public_id, student, activity_kind="post",
                    mutate=lambda s, w: post_entry_subsidiary(s, w, entry.public_id))
    session.commit()
    client.sign_in(student)

    page = _page(client, ws)

    assert "everything you have recorded is posted" in page.lower()


def test_posting_to_the_general_ledger_alone_still_leaves_the_subsidiary_outstanding(
        client, session, workspace):
    """The two ledgers are posted separately, and the entry here carries a customer."""
    ws, student = workspace
    _record(session, ws, student)
    workspace_write(session, ws.public_id, student, activity_kind="post",
                    mutate=lambda s, w: post_journal_general(s, w, "general"))
    session.commit()
    client.sign_in(student)

    page = _page(client, ws)

    assert "subsidiary" in page.lower()
    assert "General Journal" in page


def test_it_warns_but_does_not_refuse(client, session, workspace):
    """Handing in unfinished work is the student's decision. The page informs it, not blocks it."""
    ws, student = workspace
    _record(session, ws, student)
    session.commit()
    client.sign_in(student)
    page = client.get(f"/w/{ws.public_id}/testco-alpha/submit").get_data(as_text=True)
    csrf = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', page).group(1)

    client.post(f"/w/{ws.public_id}/testco-alpha/submit",
                data={"csrf_token": csrf}, follow_redirects=True)

    session.refresh(ws)
    assert ws.status == "submitted"


def test_a_voided_entry_is_not_something_left_to_post(client, session, workspace):
    """Voided entries are not posted and never will be. Counting them would send a student to a
    journal with nothing to do in it."""
    ws, student = workspace
    kept = _record(session, ws, student, key="sr-keep")
    spare = _record(session, ws, student, key="sr-void", party="C-TWO", document="INV-2")
    workspace_write(session, ws.public_id, student, activity_kind="void",
                    mutate=lambda s, w: void_entry(s, w, spare.public_id, "Recorded twice"))
    workspace_write(session, ws.public_id, student, activity_kind="post",
                    mutate=lambda s, w: post_journal_general(s, w, "general"))
    workspace_write(session, ws.public_id, student, activity_kind="post",
                    mutate=lambda s, w: post_entry_subsidiary(s, w, kept.public_id))
    session.commit()
    client.sign_in(student)

    page = _page(client, ws)

    assert "everything you have recorded is posted" in page.lower()
    assert "General Journal" not in page   # the voided one is not work left to do
