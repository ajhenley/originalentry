"""A mark that moved has to look like it moved (I3.2).

A student fixed two errors on appeal and their mark went from 72.54 to 73.45 out of a hundred.
Both screens showed "73%", because the percentage is formatted to whole numbers. The instructor
reasonably concluded that re-marking had done nothing.

Whole percentages are too coarse for a hundred-mark scheme where a single document is worth
about one and a half. One decimal place is enough to show a real change without implying a
precision the marking does not have.
"""

import re
import secrets
from datetime import UTC, datetime

import pytest
from originalentry.models import (
    Assignment,
    GradeRun,
    Section,
    SectionStaff,
    User,
    Variant,
    Workspace,
)
from originalentry.packs import schema
from originalentry.packs.importer import import_content
from sqlalchemy import select

from tests.packs import testco_alpha

pytestmark = pytest.mark.db


@pytest.fixture
def marked(session, client):
    pv = import_content(session, schema.load_pack(testco_alpha.PACK),
                        source_sha256=secrets.token_hex(32))
    variant_id = session.scalars(
        select(Variant.id).where(Variant.pack_version_id == pv.id)).first()
    section = Section(name="Sec", join_code=f"M{secrets.token_hex(3).upper()}")
    student = User(email=f"mp-{secrets.token_hex(3)}@example.edu", role="student",
                   given_name="Ada", family_name="Sowande")
    instructor = User(email=f"mi-{secrets.token_hex(3)}@example.edu", role="instructor")
    session.add_all([section, student, instructor])
    session.flush()
    # The instructor teaches this section. Without the row, scoped visibility (Task 4)
    # refuses them from their own class.
    session.add(SectionStaff(section_id=section.id, user_id=instructor.id))
    session.flush()
    assignment = Assignment(section_id=section.id, title="December", company_policy="fixed",
                            fixed_pack_version_id=pv.id)
    session.add(assignment)
    session.flush()
    # submitted_at must be set alongside the status: the grading screen's reopen panel prints
    # when the work came in, and submit_workspace always writes both.
    ws = Workspace(assignment_id=assignment.id, student_id=student.id, pack_version_id=pv.id,
                   variant_id=variant_id, status="submitted",
                   submitted_at=datetime.now(UTC))
    session.add(ws)
    session.flush()
    # A mark that rounds to the same whole percentage as its neighbour one point away.
    session.add(GradeRun(
        workspace_id=ws.id, pack_version_id=pv.id, variant_id=variant_id,
        engine_version="0.1.0", total_points=7254, max_points=10000,
        needs_review=False, submission_status="submitted", created_by_id=instructor.id,
        results={"components": [{"key": "triage", "label": "Document triage",
                                 "points": 72.54, "max_points": 100.0, "evidence": []}]},
    ))
    session.flush()
    session.commit()
    return assignment, ws, instructor


def test_the_grading_screen_shows_a_percentage_that_can_move(client, marked):
    """72.54 and 73.45 are a full point apart and both read "73%" to whole numbers."""
    assignment, _, instructor = marked
    client.sign_in(instructor)

    body = client.get(f"/staff/grading/{assignment.public_id}").get_data(as_text=True)

    assert re.search(r"72\.5\s*%", body), "the percentage is still rounded to whole numbers"


def test_one_students_screen_shows_it_too(client, marked):
    assignment, ws, instructor = marked
    client.sign_in(instructor)

    body = client.get(
        f"/staff/grading/{assignment.public_id}/{ws.public_id}").get_data(as_text=True)

    assert re.search(r"72\.5\s*%", body)
