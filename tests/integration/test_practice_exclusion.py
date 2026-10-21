"""A teacher's practice copy, and every class-level number it must stay out of.

The spec calls this "the failure to design against; everything else is recoverable": a teacher
works their own assignment in a private practice copy, and their attempts turn up in a student
gradebook -- in the progress table, in the marks CSV, in the cohort diagnostics, in a GradeRun
beside real students. An instructor would have no reason to disbelieve any of it.

So every cohort read goes through one query, ``workspaces.class_workspaces``, and
``tests/guards/test_practice_chokepoint.py`` insists that it is the only way a class-level
question is asked. This file is the other half: what that query actually does, once per screen
that reads a cohort. The guard proves the nine sites are wired to one place; these prove the one
place answers correctly, and ``test_each_of_these_sees_the_student`` proves it does not answer
correctly by returning nothing.

The world is the real shape: **one** assignment with a student's workspace and the teacher's
practice copy on it, which is what a teacher setting their own assignment ends up with. The unique
index on (assignment, student) does not collide, because a practice copy's ``student_id`` is the
teacher's own id.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from originalentry.models import (
    ROLE_INSTRUCTOR,
    Assignment,
    ContentPack,
    GradeRun,
    PackVersion,
    Section,
    SectionStaff,
    User,
    Variant,
    Workspace,
)
from originalentry.packs import schema
from originalentry.packs.importer import import_answer_keys, import_content
from originalentry.services.assignments import ROUND_ROBIN, open_workspace, variant_for
from originalentry.services.diagnostics import cohort_diagnostics
from originalentry.services.grades import grade_section
from originalentry.services.marks_export import marks_csv
from originalentry.services.mastery import assignment_mastery
from originalentry.services.progress import assignment_progress
from originalentry.staff.views import live_workspace_counts
from sqlalchemy import func, select

from tests.packs import testco_alpha

pytestmark = pytest.mark.db


def _user(email: str, *, role: str | None = None, family_name: str = "Sowande") -> User:
    user = User(email=email, given_name="Ada", family_name=family_name)
    if role is not None:
        user.role = role
    return user


@pytest.fixture
def world(session):
    """One assignment, one student's books, and the teacher's practice copy of the same books.

    A **second** variant is added to the pack, which the fixture pack does not declare. The
    round-robin count is the one cohort read whose bug is not cosmetic -- it decides which variant
    the next student to join is handed -- and with a single variant in the pack, ``taken % 1`` is
    zero however many workspaces are counted, so the test for it could not fail.

    And a **second assignment**, with a second student's books on it. Without it every test in
    this file held one assignment, so a cohort read that lost its assignment filter altogether --
    one token, and the shape ``class_workspace_clause(ALL_ASSIGNMENTS)`` now guards against --
    would pass all eleven unchanged while listing another class's students. The practice copy is
    the failure this file is named for; a lost assignment filter is the one it could not see.

    "Unchanged" was measured, and the measurement found something worth writing down: with the
    filter dropped and no second assignment here, two of these tests still failed -- but they
    failed on a ``demo-student`` row that lives in the shared Neon development branch, outside
    this test's transaction. So the old fixture caught a lost filter only when the shared database
    happened to hold somebody else's workspaces, which is the exact coupling commit cb61565
    ("two tests coupled to what the shared database happens to hold") was written to remove. The
    second assignment makes the detection the fixture's own, and deterministic.
    """
    pack_version = import_content(session, schema.load_pack(testco_alpha.PACK),
                                  source_sha256="excl" + "0" * 60)
    import_answer_keys(session, pack_version,
                       {"A": schema.load_answer_key(testco_alpha.KEY_A)})
    variant_a = session.scalars(
        select(Variant).where(Variant.pack_version_id == pack_version.id)).one()
    variant_b = Variant(pack_version_id=pack_version.id, code="B", label="Variant B",
                        driver_values={})
    session.add(variant_b)

    section = Section(name="Sec", join_code="excl-join")
    teacher = _user("exclusion-teacher@example.edu", role=ROLE_INSTRUCTOR,
                    family_name="Teacherson")
    student = _user("exclusion-student@example.edu", family_name="Studentson")
    session.add_all([section, teacher, student])
    session.flush()
    session.add(SectionStaff(section_id=section.id, user_id=teacher.id))
    assignment = Assignment(section_id=section.id, title="December", company_policy="fixed",
                            fixed_pack_version_id=pack_version.id,
                            variant_policy=ROUND_ROBIN)
    session.add(assignment)
    session.flush()

    other_assignment = Assignment(section_id=section.id, title="November",
                                  company_policy="fixed",
                                  fixed_pack_version_id=pack_version.id,
                                  variant_policy=ROUND_ROBIN)
    other_student = _user("exclusion-other-student@example.edu", family_name="Othersson")
    session.add_all([other_assignment, other_student])
    session.flush()
    other_workspace = Workspace(assignment_id=other_assignment.id, student_id=other_student.id,
                                pack_version_id=pack_version.id, variant_id=variant_a.id,
                                status="in_progress")
    session.add(other_workspace)

    student_workspace = Workspace(assignment_id=assignment.id, student_id=student.id,
                                  pack_version_id=pack_version.id, variant_id=variant_a.id,
                                  status="in_progress")
    practice = Workspace(assignment_id=assignment.id, student_id=teacher.id,
                         pack_version_id=pack_version.id, variant_id=variant_a.id,
                         # Submitted, so a practice copy that leaked in would move the submitted
                         # rate as well as the head count -- one assertion catching two failures.
                         status="submitted", staff_practice=True)
    session.add_all([student_workspace, practice])
    session.flush()
    version = session.get(PackVersion, pack_version.id)
    return {
        "teacher": teacher, "student": student, "assignment": assignment,
        "practice": practice, "student_workspace": student_workspace,
        "other_assignment": other_assignment, "other_student": other_student,
        "other_workspace": other_workspace,
        "pack_version": pack_version, "variant_a": variant_a, "variant_b": variant_b,
        "slug": session.get(ContentPack, version.content_pack_id).slug,
    }


def _grading_page(client, world) -> str:
    client.sign_in(world["teacher"])
    response = client.get(f"/staff/grading/{world['assignment'].public_id}")
    assert response.status_code == 200, "the grading page did not open"
    return response.get_data(as_text=True)


def _runs_for(session, workspace) -> int:
    return session.execute(
        select(func.count()).select_from(GradeRun).where(GradeRun.workspace_id == workspace.id)
    ).scalar_one()


# ── one per cohort read ────────────────────────────────────────────────────────────────

def test_the_progress_table_does_not_list_the_practice_copy(session, world):
    rows = assignment_progress(session, world["assignment"])

    assert [row.student_email for row in rows] == [world["student"].email]


def test_the_marks_csv_does_not_carry_the_practice_copy(session, world):
    csv = marks_csv(session, world["assignment"])

    assert world["student"].email in csv, "the export lost the student"
    assert world["teacher"].email not in csv
    assert world["other_student"].email not in csv, "the export reaches another assignment"


def test_the_cohort_diagnostics_ignore_the_practice_copy(session, world):
    assert cohort_diagnostics(session, world["assignment"]).total == 1


def test_the_mastery_view_ignores_the_practice_copy(session, world):
    """Including it would move the submitted rate and every concept's share of marks."""
    report = assignment_mastery(session, world["assignment"])

    assert (report.submitted, report.total) == (0, 1)


def test_the_cohort_grading_run_skips_the_practice_copy(session, world):
    """No GradeRun for it from grade_section, so it never sits in the class's grading records."""
    graded, total, _ = grade_section(session, world["assignment"], actor=world["teacher"])

    assert total == 1, "the section size counts the practice copy"
    assert _runs_for(session, world["practice"]) == 0
    assert len(graded) == 1 and graded[0].workspace_id == world["student_workspace"].id


def test_the_grading_roster_does_not_list_the_practice_copy(client, session, world):
    body = _grading_page(client, world)

    assert world["student_workspace"].public_id in body, "the roster lost the student"
    assert world["practice"].public_id not in body
    assert world["other_workspace"].public_id not in body, "the roster reaches another assignment"


def test_the_archived_books_list_does_not_list_the_practice_copy(client, session, world):
    when = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    world["practice"].archived_at = when
    world["student_workspace"].archived_at = when
    session.flush()

    body = _grading_page(client, world)

    assert world["student_workspace"].public_id in body, "the archived list lost the student"
    assert world["practice"].public_id not in body
    assert world["other_workspace"].public_id not in body, \
        "the archived list reaches another assignment"


def test_the_round_robin_count_ignores_the_practice_copy(session, world):
    """Review Focus 4. assignments.py:312 counts live workspaces, so a practice copy shifts
    which variant the NEXT student is handed -- a correctness bug, not a cosmetic one."""
    handed_out = variant_for(session, world["assignment"], world["pack_version"].id)

    assert handed_out == world["variant_b"].id, (
        "with one student in, the next student gets the second variant; counting the practice "
        "copy hands them the first one again"
    )


def test_the_assignment_list_count_does_not_count_the_practice_copy(client, session, world):
    """The console's own per-assignment figure, which the column header calls students.

    Not in the task brief's nine: it is a ``select``/``group_by`` pair with no comparison at all,
    found by the guard rather than by the enumeration, and it was telling a teacher of three
    students that they had four.
    """
    counts = live_workspace_counts()

    assert counts.get(world["assignment"].id) == 1
    # The one caller that really does span every assignment, so the other one has to be in there
    # too: a count keyed per assignment is not evidence that the keying works.
    assert counts.get(world["other_assignment"].id) == 1


# ── the two guards from the inside ─────────────────────────────────────────────────────

def test_each_of_these_sees_the_student(client, session, world):
    """Guards all eight from the inside: excluding everything would pass them."""
    student, assignment = world["student"], world["assignment"]
    seen = {
        "progress": [r.student_email for r in assignment_progress(session, assignment)],
        "marks csv": [student.email] if student.email in marks_csv(session, assignment) else [],
        "diagnostics": [student.email] * cohort_diagnostics(session, assignment).total,
        "mastery": [student.email] * assignment_mastery(session, assignment).total,
        "roster": [student.email] if student.email in _grading_page(client, world) else [],
        "console count": [student.email] * (live_workspace_counts().get(assignment.id) or 0),
    }
    graded, _, _ = grade_section(session, assignment, actor=world["teacher"])
    seen["grading run"] = [student.email] * len(graded)
    seen["round robin"] = (
        [student.email] if variant_for(session, assignment, world["pack_version"].id)
        == world["variant_b"].id else [])

    blind = sorted(where for where, found in seen.items() if found != [student.email])
    assert not blind, f"these stopped seeing the student altogether: {blind}"


def test_a_teacher_still_reaches_their_own_copy(session, world):
    """The per-person queries must NOT exclude. student/views.py:252 is how a teacher gets back
    to it from their own workspace list, and ``open_workspace`` is the same shape: it answers
    "this person's live workspace on this assignment", and an exclusion here would both hide the
    copy and let a second one be opened over the top of it.
    """
    assert open_workspace(session, world["assignment"], world["teacher"]) is world["practice"]
    assert open_workspace(session, world["assignment"], world["student"]) \
        is world["student_workspace"]
