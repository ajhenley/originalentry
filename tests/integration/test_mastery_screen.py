"""Mastery against a real database: who is counted, and whose marks.

The arithmetic is pinned without a database in tests/unit/test_mastery.py. What needs Postgres is
everything about *which* workspaces and *which* marks: the population rule, grade overrides, and
(from Task 4) the scoping and the screen.
"""

from __future__ import annotations

import pytest
from originalentry.grading.workspace import grade_workspace
from originalentry.models import Assignment, Section, User, Variant, Workspace
from originalentry.packs import schema
from originalentry.packs.importer import import_answer_keys, import_content
from originalentry.services.grades import record_run, set_override
from originalentry.services.mastery import SUPPORT_THRESHOLD, assignment_mastery
from originalentry.services.submit import submit_workspace
from sqlalchemy import select

from tests.packs import testco_alpha

pytestmark = pytest.mark.db


def _world(session, *, students: int = 1, join_code: str = "mastery-join"):
    """An assignment with `students` workspaces on it, nothing submitted yet."""
    pack_version = import_content(
        session, schema.load_pack(testco_alpha.PACK), source_sha256="y" * 64)
    import_answer_keys(session, pack_version, {"A": schema.load_answer_key(testco_alpha.KEY_A)})
    variant = session.scalars(
        select(Variant).where(Variant.pack_version_id == pack_version.id)).first()
    section = Section(name="Mastery Sec", join_code=join_code)
    grader = User(email=f"grader-{join_code}@example.edu", role="grader")
    session.add_all([section, grader])
    session.flush()
    assignment = Assignment(section_id=section.id, title="December", company_policy="fixed",
                            fixed_pack_version_id=pack_version.id)
    session.add(assignment)
    session.flush()

    workspaces = []
    for index in range(students):
        student = User(email=f"stu{index}-{join_code}@example.edu")
        session.add(student)
        session.flush()
        workspace = Workspace(assignment_id=assignment.id, student_id=student.id,
                              pack_version_id=pack_version.id, variant_id=variant.id,
                              status="in_progress")
        session.add(workspace)
        session.flush()
        workspaces.append(workspace)
    session.commit()
    return assignment, workspaces, grader


def _submit_and_grade(session, workspace, grader):
    submit_workspace(session, workspace)
    record_run(session, workspace, grade_workspace(session, workspace), created_by=grader)
    session.commit()


def test_an_assignment_with_nothing_submitted_reports_zeroes_and_no_weakest(session):
    """Review Focus 1. A brand-new assignment has nobody in the population: the report must
    render rather than divide by zero, and the screen must have no callout to draw."""
    assignment, _workspaces, _grader = _world(session, join_code="mastery-empty")

    report = assignment_mastery(session, assignment)

    assert report.submitted == 0
    assert report.total == 1
    assert report.concepts == ()
    assert report.weakest is None
    assert report.needs_support == 0


def test_only_submitted_work_counts(session):
    """A component's max_points is always the pack's full weight, so an unsubmitted workspace
    would contribute 0/full to every concept it touches and drag every percentage toward zero."""
    assignment, workspaces, grader = _world(session, students=2, join_code="mastery-open")
    _submit_and_grade(session, workspaces[0], grader)
    # workspaces[1] is left open and ungraded.

    report = assignment_mastery(session, assignment)

    assert (report.submitted, report.total) == (1, 2)
    assert report.concepts, "the submitted workspace produced no concepts"


def test_a_reopened_workspace_drops_out_of_the_population(session):
    """Reopened work is in flux, so its marks are provisional and must not weigh on the class's
    mastery.

    This is where the three candidate definitions of "submitted" actually disagree, and not in the
    direction the plan claimed: submission_status branches on `status == "submitted"`, so it and
    `status` both exclude reopened work, while `submitted_at is not None` would include it. The
    population names the function for the lateness and closed-never-handed-in semantics it adds,
    not because it disagrees with `status`.
    """
    assignment, workspaces, grader = _world(session, join_code="mastery-reopen")
    _submit_and_grade(session, workspaces[0], grader)
    assert assignment_mastery(session, assignment).submitted == 1

    workspaces[0].status = "in_progress"      # what reopening leaves behind
    session.commit()

    assert assignment_mastery(session, assignment).submitted == 0


def test_an_override_moves_the_concept_it_belongs_to(session):
    """Review Focus 4. final_marks applies overrides, and the CSV on this screen already shows
    them -- a figure that ignored them would contradict the export beside it."""
    assignment, workspaces, grader = _world(session, join_code="mastery-override")
    _submit_and_grade(session, workspaces[0], grader)
    before = {c.key: c.points for c in assignment_mastery(session, assignment).concepts}
    # Overridden UPWARD on purpose. This student submitted an untouched workspace, so every
    # component already scores zero -- an override to zero would change nothing and the test
    # could not fail, whatever the implementation did with overrides.
    assert before["document_triage"] == 0.0, "fixture no longer starts from zero; pick another way"

    set_override(session, workspaces[0], "triage", points=7.5,
                 reason="Raised by hand, to prove mastery reads final_marks", actor=grader)
    session.commit()

    after = {c.key: c.points for c in assignment_mastery(session, assignment).concepts}
    assert after["document_triage"] == 7.5, (
        f"triage mastery ignored the override: {before['document_triage']} -> "
        f"{after['document_triage']}")


def test_needs_support_counts_students_below_the_threshold(session):
    """Counted over the submitted population, from the same final marks as the percentage."""
    assignment, workspaces, grader = _world(session, join_code="mastery-support")
    _submit_and_grade(session, workspaces[0], grader)
    marks_before = assignment_mastery(session, assignment)

    # Drive this student below the line by hand, whatever the pack's own marks came to.
    for component in ("triage", "entry_accuracy"):
        set_override(session, workspaces[0], component, points=0.0,
                     reason="Below the support line on purpose", actor=grader)
    session.commit()

    after = assignment_mastery(session, assignment)
    assert after.needs_support == 1, (
        f"threshold is {SUPPORT_THRESHOLD}; before={marks_before.needs_support} after="
        f"{after.needs_support}")
