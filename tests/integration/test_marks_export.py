"""Marks export (I5.1): both presets carry late_hours and submission_status."""

import copy
import secrets

import pytest
from originalentry.models import Enrollment, Section, User, Variant, Workspace
from originalentry.packs import schema
from originalentry.packs.importer import import_answer_keys, import_content
from originalentry.services.assignments import create_assignment
from originalentry.services.grades import grade_section
from originalentry.services.marks_export import marks_csv
from sqlalchemy import select

from tests.packs import testco_alpha

pytestmark = pytest.mark.db


def _graded(session):
    data = copy.deepcopy(testco_alpha.PACK)
    data["company"]["slug"] = f"marks-{secrets.token_hex(3)}"
    pv = import_content(session, schema.load_pack(data), source_sha256=secrets.token_hex(32))
    import_answer_keys(session, pv, {"A": schema.load_answer_key(testco_alpha.KEY_A)})
    section = Section(name="Sec", join_code=f"K{secrets.token_hex(3).upper()}")
    student = User(email=f"mk-{secrets.token_hex(3)}@example.edu", role="student",
                   given_name="Mara", family_name="Keys")
    session.add_all([section, student])
    session.flush()
    session.add(Enrollment(section_id=section.id, user_id=student.id, student_number="S-42"))
    assignment = create_assignment(session, section=section, title="December cycle",
                                   pack_version=pv)
    # A workspace on the section's variant, so there is something to grade.
    variant = session.scalars(select(Variant).where(Variant.pack_version_id == pv.id)).first()
    ws = Workspace(assignment_id=assignment.id, student_id=student.id, pack_version_id=pv.id,
                   variant_id=variant.id, status="in_progress")
    session.add(ws)
    session.flush()
    grade_section(session, assignment)
    return assignment, student


def test_generic_csv_has_the_facts(session):
    assignment, student = _graded(session)
    text = marks_csv(session, assignment, "generic")
    header = text.splitlines()[0]
    assert "late_hours" in header and "submission_status" in header
    assert student.email in text and "S-42" in text


def test_canvas_csv_names_the_assignment(session):
    assignment, student = _graded(session)
    text = marks_csv(session, assignment, "canvas")
    header = text.splitlines()[0]
    assert "SIS Login ID" in header and assignment.title in header
    assert "late_hours" in header and "submission_status" in header
    assert student.email in text
