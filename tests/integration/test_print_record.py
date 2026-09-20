"""The print record (T10.5): the whole workspace record on one page for the browser to save as
PDF. The service assembles it; the page renders every section and says nothing it may not (A7)."""

import copy
import re
import secrets
from datetime import date

import pytest
from originalentry.models import Section, User
from originalentry.packs import schema
from originalentry.packs.importer import import_content
from originalentry.services import workspace_write
from originalentry.services.assignments import create_assignment, open_workspace
from originalentry.services.entries import record_entry
from originalentry.services.posting import post_journal_general
from originalentry.services.record import workspace_record

from tests.packs import testco_alpha

pytestmark = pytest.mark.db

BANNED = re.compile(r"\b(correct|incorrect|right|wrong)\b", re.IGNORECASE)


def _visible(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def _seed(session):
    data = copy.deepcopy(testco_alpha.PACK)
    data["company"]["slug"] = f"print-{secrets.token_hex(3)}"
    pv = import_content(session, schema.load_pack(data), source_sha256=secrets.token_hex(32))
    section = Section(name="Sec", join_code=f"P{secrets.token_hex(3).upper()}")
    student = User(email=f"p-{secrets.token_hex(3)}@example.edu", role="student")
    session.add_all([section, student])
    session.flush()
    assignment = create_assignment(session, section=section, title="Dec", pack_version=pv)
    ws = open_workspace(session, assignment, student)

    from originalentry.forms.entries import EntryCommand, LineCommand
    cmd = EntryCommand(journal_key="general", kind="regular", document_ref="INV-1",
                       entry_date=date(2026, 12, 2), description="Sale",
                       lines=[LineCommand("112", "C-ONE", 120000, 0),
                              LineCommand("401", None, 0, 120000)],
                       client_key="p1")
    workspace_write(session, ws.public_id, student, activity_kind="save",
                    mutate=lambda s, w: record_entry(s, w, cmd))
    workspace_write(session, ws.public_id, student, activity_kind="post",
                    mutate=lambda s, w: post_journal_general(s, w, "general"))
    return student, ws, pv


def test_record_assembles_the_whole_thing(session):
    from originalentry.models import PackVersion

    _, ws, pv = _seed(session)
    pv_row = session.get(PackVersion, pv.id)
    record = workspace_record(session, ws, pv_row.manifest or {}, ("customer",))

    assert set(record.trial_balances) == {"unadjusted", "adjusted", "post_closing"}
    assert record.trial_balances["unadjusted"].in_balance
    assert record.general_ledger  # posted balances present
    assert any(j["entries"] for j in record.journals)
    assert record.postings and record.postings[0]["target"] == "general"
    assert record.timeline  # save + post recorded


def test_print_page_renders(client, session):
    from originalentry.models import ContentPack, PackVersion

    student, ws, _ = _seed(session)
    client.sign_in(student)
    pv = session.get(PackVersion, ws.pack_version_id)
    slug = session.get(ContentPack, pv.content_pack_id).slug

    resp = client.get(f"/w/{ws.public_id}/{slug}/print")
    assert resp.status_code == 200
    text = _visible(resp.get_data(as_text=True))
    for heading in ("Documents", "Journals", "General ledger", "Trial balances", "Checkpoints",
                    "Timeline"):
        assert heading in text
    assert "In balance" in text
    assert not BANNED.search(text)
