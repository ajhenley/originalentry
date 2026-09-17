"""Disposition (triage) writes: record, no-entry-needs-reason, and supersession keeping one
current row per document (partial unique index, tension 9)."""

import pytest
from parchment.models import Assignment, Disposition, Section, User, Variant, Workspace
from parchment.packs import schema
from parchment.packs.importer import import_content
from parchment.services import WriteRefused, workspace_write
from parchment.services.dispositions import current_dispositions, set_disposition
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
