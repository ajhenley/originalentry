"""What a student sees once marks are released (S6.6).

Before release there is nothing to see, and the page says so plainly. After release the student
sees the points for each component and the instructor's comment — worded as marks awarded, never
in the four words the interface never uses (A7).
"""

import re
from datetime import UTC, datetime

import pytest
from parchment.grading.workspace import grade_workspace
from parchment.models import Assignment, Section, User, Variant, Workspace
from parchment.packs import schema
from parchment.packs.importer import import_answer_keys, import_content
from parchment.services.grades import record_run, set_comment, set_override
from sqlalchemy import select

from tests.packs import testco_alpha

pytestmark = pytest.mark.db

BANNED = re.compile(r"\b(correct|incorrect|right|wrong)\b", re.IGNORECASE)


@pytest.fixture
def graded(session, client):
    pv = import_content(session, schema.load_pack(testco_alpha.PACK), source_sha256="v" * 64)
    import_answer_keys(session, pv, {"A": schema.load_answer_key(testco_alpha.KEY_A)})
    variant = session.scalars(select(Variant).where(Variant.pack_version_id == pv.id)).first()
    section = Section(name="Sec", join_code="marks-view")
    student = User(email="marksview@example.edu")
    grader = User(email="grader-marksview@example.edu", role="grader")
    session.add_all([section, student, grader])
    session.flush()
    asg = Assignment(section_id=section.id, title="December", company_policy="fixed",
                     fixed_pack_version_id=pv.id)
    session.add(asg)
    session.flush()
    ws = Workspace(assignment_id=asg.id, student_id=student.id, pack_version_id=pv.id,
                   variant_id=variant.id, status="in_progress")
    session.add(ws)
    session.flush()
    record_run(session, ws, grade_workspace(session, ws), created_by=grader)
    set_comment(session, ws, "Your subsidiary proof was tidy.", actor=grader)
    client.sign_in(student)
    return ws, asg


def _visible_text(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def _url(ws):
    return f"/w/{ws.public_id}/testco-alpha/marks"


def test_before_release_the_page_says_there_is_nothing_to_show_yet(client, graded):
    ws, _ = graded

    body = client.get(_url(ws)).get_data(as_text=True)

    assert "not been released" in body
    assert "Your subsidiary proof was tidy." not in body  # the comment waits for release
    assert not BANNED.search(_visible_text(body))


def test_after_release_the_student_sees_each_component_and_the_comment(client, graded, session):
    ws, assignment = graded
    assignment.marks_released_at = datetime.now(UTC)
    session.flush()

    body = client.get(_url(ws)).get_data(as_text=True)

    assert "Document triage" in body
    assert "Your subsidiary proof was tidy." in body
    assert "of 100" in body
    assert not BANNED.search(_visible_text(body))


def test_an_overridden_component_shows_the_mark_the_instructor_gave(client, graded, session):
    ws, assignment = graded
    assignment.marks_released_at = datetime.now(UTC)
    set_override(session, ws, "triage", points=8.0, reason="Marked by hand", actor=None)
    session.flush()

    body = client.get(_url(ws)).get_data(as_text=True)

    assert "8" in body
    assert "Marked by hand" in body  # the student is told why their mark was changed
