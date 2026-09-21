"""Disposition (triage) writes: record, no-entry-needs-reason, and supersession keeping one
current row per document (partial unique index, tension 9)."""

import re

import pytest
from originalentry.models import Assignment, Disposition, Section, User, Variant, Workspace
from originalentry.packs import schema
from originalentry.packs.importer import import_content
from originalentry.services import WriteRefused, workspace_write
from originalentry.services.dispositions import current_dispositions, set_disposition
from sqlalchemy import func, select

from tests.packs import testco_alpha

pytestmark = pytest.mark.db


def _seed(session):
    pv = import_content(session, schema.load_pack(testco_alpha.PACK), source_sha256="d" * 64)
    variant = session.scalars(select(Variant).where(Variant.pack_version_id == pv.id)).first()
    section = Section(name="Sec", join_code="disp-join")
    student = User(email="disp@example.edu")
    session.add_all([section, student])
    session.flush()
    asg = Assignment(section_id=section.id, title="Dec", company_policy="fixed",
                     fixed_pack_version_id=pv.id)
    session.add(asg)
    session.flush()
    ws = Workspace(assignment_id=asg.id, student_id=student.id, pack_version_id=pv.id,
                   variant_id=variant.id, status="in_progress")
    session.add(ws)
    session.flush()
    return ws, student


def _current_count(session, ws):
    return session.execute(
        select(func.count()).select_from(Disposition).where(
            Disposition.workspace_id == ws.id, Disposition.superseded_at.is_(None)
        )
    ).scalar_one()


def test_record_then_change_to_no_entry_supersedes(session):
    ws, student = _seed(session)

    workspace_write(session, ws.public_id, student, activity_kind="disposition",
                    mutate=lambda s, w: set_disposition(s, w, "INV-1", "record", None))
    current = current_dispositions(session, ws)
    assert len(current) == 1
    assert next(iter(current.values())).choice == "record"

    # Change the mind to "no entry required" with a reason.
    workspace_write(session, ws.public_id, student, activity_kind="disposition",
                    mutate=lambda s, w: set_disposition(s, w, "INV-1", "no_entry", "duplicate"))

    assert _current_count(session, ws) == 1  # exactly one current row survives
    total = session.execute(
        select(func.count()).select_from(Disposition).where(Disposition.workspace_id == ws.id)
    ).scalar_one()
    assert total == 2  # the old row is kept, superseded
    current = current_dispositions(session, ws)
    disp = next(iter(current.values()))
    assert disp.choice == "no_entry" and disp.reason == "duplicate"


def test_no_entry_requires_a_reason(session):
    ws, student = _seed(session)
    with pytest.raises(WriteRefused):
        workspace_write(session, ws.public_id, student, activity_kind="disposition",
                        mutate=lambda s, w: set_disposition(s, w, "INV-1", "no_entry", "  "))
    assert _current_count(session, ws) == 0


# ── Changing your mind ──────────────────────────────────────────────────────────────────
#
# Reported as "there doesn't seem to be a way to change your mind". There was: both choices stay
# on the page and the service supersedes the old one, which the test above proves. What there was
# not, was any sign of it. The page said "Current choice: Record an entry" and then showed the
# same two buttons underneath, which reads as a record of what you picked rather than something
# you can still alter.


def _post_choice(client, ws, choice, reason=None):
    page = client.get(f"/w/{ws.public_id}/testco-alpha/documents/INV-1").get_data(as_text=True)
    csrf = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', page).group(1)
    data = {"csrf_token": csrf, "choice": choice}
    if reason:
        data["reason"] = reason
    return client.post(
        f"/w/{ws.public_id}/testco-alpha/documents/INV-1/disposition",
        data=data, follow_redirects=True,
    ).get_data(as_text=True)


def _handle_section(client, ws) -> str:
    """Only the part of the page that handles the document.

    Scoped deliberately: the save banner carries the word "changed" in a data attribute, so an
    assertion against the whole page passes whatever the section says.
    """
    body = client.get(f"/w/{ws.public_id}/testco-alpha/documents/INV-1").get_data(as_text=True)
    start = body.index("What does this document need") if "What does this document need" in body \
        else body.index("Handle this document")
    return body[start:]


def test_the_section_says_the_choice_can_be_changed(client, session):
    ws, student = _seed(session)
    session.commit()
    client.sign_in(student)
    _post_choice(client, ws, "record")

    section = _handle_section(client, ws)

    assert "change" in section.lower()


def test_the_option_already_chosen_is_marked_beside_it(client, session):
    """A sentence above two identical buttons does not say which button is in force."""
    ws, student = _seed(session)
    session.commit()
    client.sign_in(student)
    _post_choice(client, ws, "record")

    section = _handle_section(client, ws)
    record_form = section[section.index('value="record"'):]

    assert "Current" in record_form[:400]


def test_switching_to_no_entry_through_the_screen_works(client, session):
    ws, student = _seed(session)
    session.commit()
    client.sign_in(student)
    _post_choice(client, ws, "record")

    body = _post_choice(client, ws, "no_entry", reason="On reflection it is a quotation")

    assert "On reflection it is a quotation" in body


def test_switching_back_again_clears_the_reason(client, session):
    ws, student = _seed(session)
    session.commit()
    client.sign_in(student)
    _post_choice(client, ws, "no_entry", reason="A quotation")

    body = _post_choice(client, ws, "record")

    assert "A quotation" not in body
