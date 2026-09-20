"""Storing what the engine decided (T8.1, I3.2–I3.5, A12).

A grade run is immutable: regrading adds a run, it never edits one. An override is a separate
record with a reason, and it survives a regrade — otherwise an instructor's judgement would be
undone by the next run of the engine, which is exactly the bug A12 exists to catch.
"""

from dataclasses import replace

import pytest
from originalentry.grading.models import Deduction
from originalentry.grading.workspace import grade_workspace
from originalentry.models import Assignment, GradeRun, Section, User, Variant, Workspace
from originalentry.packs import schema
from originalentry.packs.importer import import_answer_keys, import_content
from originalentry.services import workspace_write
from originalentry.services.dispositions import set_disposition
from originalentry.services.grades import (
    final_marks,
    from_hundredths,
    latest_run,
    record_run,
    set_comment,
    set_override,
)
from originalentry.services.submit import submit_workspace
from sqlalchemy import func, select

from tests.packs import testco_alpha

pytestmark = pytest.mark.db


def _seed(session, email="marks@example.edu", join_code="marks-join"):
    pv = import_content(session, schema.load_pack(testco_alpha.PACK), source_sha256="m" * 64)
    import_answer_keys(session, pv, {"A": schema.load_answer_key(testco_alpha.KEY_A)})
    variant = session.scalars(select(Variant).where(Variant.pack_version_id == pv.id)).first()
    section = Section(name="Sec", join_code=join_code)
    student = User(email=email)
    grader = User(email=f"grader-{email}", role="grader")
    session.add_all([section, student, grader])
    session.flush()
    asg = Assignment(section_id=section.id, title="Dec", company_policy="fixed",
                     fixed_pack_version_id=pv.id)
    session.add(asg)
    session.flush()
    ws = Workspace(assignment_id=asg.id, student_id=student.id, pack_version_id=pv.id,
                   variant_id=variant.id, status="in_progress")
    session.add(ws)
    session.flush()
    return ws, student, grader


def _grade_and_store(session, ws, grader):
    return record_run(session, ws, grade_workspace(session, ws), created_by=grader)


def test_a_run_keeps_the_points_and_the_evidence_behind_them(session):
    ws, student, grader = _seed(session)
    workspace_write(session, ws.public_id, student, activity_kind="disposition",
                    mutate=lambda s, w: set_disposition(s, w, "INV-1", "record", None))

    run = _grade_and_store(session, ws, grader)

    # Points are stored in hundredths, as money is stored in cents (D1).
    assert from_hundredths(run.max_points) == 100
    stored = latest_run(session, ws)
    assert stored.id == run.id
    triage = stored.result.component("triage")
    assert triage.points == pytest.approx(triage.max_points / 2)
    assert any("INV-1" in row.item for row in triage.evidence)


def test_regrading_adds_a_run_and_never_edits_one(session):
    ws, student, grader = _seed(session)
    first = _grade_and_store(session, ws, grader)
    workspace_write(session, ws.public_id, student, activity_kind="disposition",
                    mutate=lambda s, w: set_disposition(s, w, "INV-1", "record", None))

    second = _grade_and_store(session, ws, grader)

    assert second.id != first.id
    assert first.total_points < second.total_points
    assert session.execute(
        select(func.count()).select_from(GradeRun).where(GradeRun.workspace_id == ws.id)
    ).scalar_one() == 2
    assert latest_run(session, ws).id == second.id


def test_an_override_changes_the_mark_and_records_its_reason(session):
    ws, _, grader = _seed(session)
    _grade_and_store(session, ws, grader)

    set_override(session, ws, "triage", points=7.5, reason="Reasons accepted on appeal",
                 actor=grader)

    marks = final_marks(session, ws)
    triage = next(c for c in marks.components if c.key == "triage")
    assert triage.points == 7.5
    assert triage.overridden
    assert triage.reason == "Reasons accepted on appeal"
    assert marks.total_points == pytest.approx(7.5)  # nothing else earned anything


def test_an_override_survives_a_regrade(session):
    """A12: the engine must not undo an instructor's judgement."""
    ws, student, grader = _seed(session)
    _grade_and_store(session, ws, grader)
    set_override(session, ws, "triage", points=9.0, reason="Marked by hand", actor=grader)

    workspace_write(session, ws.public_id, student, activity_kind="disposition",
                    mutate=lambda s, w: set_disposition(s, w, "INV-1", "record", None))
    _grade_and_store(session, ws, grader)

    marks = final_marks(session, ws)
    triage = next(c for c in marks.components if c.key == "triage")
    assert triage.points == 9.0
    assert triage.reason == "Marked by hand"


def test_a_second_override_supersedes_the_first(session):
    ws, _, grader = _seed(session)
    _grade_and_store(session, ws, grader)
    set_override(session, ws, "triage", points=4.0, reason="First look", actor=grader)

    set_override(session, ws, "triage", points=6.0, reason="Second look", actor=grader)

    marks = final_marks(session, ws)
    triage = next(c for c in marks.components if c.key == "triage")
    assert triage.points == 6.0
    assert triage.reason == "Second look"


def test_an_override_needs_a_reason(session):
    ws, _, grader = _seed(session)
    _grade_and_store(session, ws, grader)

    with pytest.raises(ValueError):
        set_override(session, ws, "triage", points=1.0, reason="  ", actor=grader)


def test_a_run_records_how_the_work_was_handed_in(session):
    ws, student, grader = _seed(session)
    assert _grade_and_store(session, ws, grader).submission_status == "open"

    workspace_write(session, ws.public_id, student, activity_kind="submit",
                    mutate=lambda s, w: submit_workspace(s, w))

    assert _grade_and_store(session, ws, grader).submission_status == "submitted"


def test_a_comment_is_kept_for_the_student_to_read_after_release(session):
    ws, _, grader = _seed(session)
    _grade_and_store(session, ws, grader)

    set_comment(session, ws, "Your subsidiary proof was tidy.", actor=grader)

    assert final_marks(session, ws).comment == "Your subsidiary proof was tidy."


# ── A deduction the pack asked for, all the way through (T8.5) ──────────────────────────
#
# The engine applies it; these check it survives storage and the override pass. The mark an
# instructor reads must equal the mark that was stored — a total that quietly disagrees with the
# sum of its own components is worse than no total at all.

def _run_with_deduction(session, ws, student, grader, points=4.0):
    """A run the pack asked a deduction for. The engine's own rule is covered in the unit tests;
    what these check is that the number survives storage and the override pass.

    The student earns something first: a deduction against nothing only proves the clamp."""
    workspace_write(session, ws.public_id, student, activity_kind="disposition",
                    mutate=lambda s, w: set_disposition(s, w, "INV-1", "record", None))
    result = grade_workspace(session, ws)
    asked = replace(
        result,
        deductions=(Deduction("sale_to_an_expense_account", "Recorded a sale in an expense",
                              points),),
    )
    return record_run(session, ws, asked, created_by=grader)


def test_a_deduction_is_stored_with_the_run(session):
    ws, student, grader = _seed(session, email="ded1@example.edu", join_code="ded1-join")

    run = _run_with_deduction(session, ws, student, grader)

    stored = latest_run(session, ws)
    assert [d.label for d in stored.result.deductions] == ["Recorded a sale in an expense"]
    assert from_hundredths(run.total_points) == stored.result.total_points


def test_the_mark_an_instructor_reads_includes_it(session):
    ws, student, grader = _seed(session, email="ded2@example.edu", join_code="ded2-join")
    run = _run_with_deduction(session, ws, student, grader, points=4.0)

    marks = final_marks(session, ws)

    assert marks.deducted_points == 4.0
    assert marks.total_points == sum(c.points for c in marks.components) - 4.0
    assert marks.total_points == from_hundredths(run.total_points)


def test_an_override_still_wins_on_its_own_component(session):
    """A grader's judgement is not undone by a deduction, and does not erase it either."""
    ws, student, grader = _seed(session, email="ded3@example.edu", join_code="ded3-join")
    _run_with_deduction(session, ws, student, grader, points=4.0)

    set_override(session, ws, "triage", points=10.0, reason="Marked by hand", actor=grader)

    marks = final_marks(session, ws)
    triage = next(c for c in marks.components if c.key == "triage")
    assert triage.points == 10.0
    assert marks.deducted_points == 4.0


def test_a_deduction_never_makes_the_mark_negative(session):
    ws, student, grader = _seed(session, email="ded4@example.edu", join_code="ded4-join")

    _run_with_deduction(session, ws, student, grader, points=1000.0)

    assert final_marks(session, ws).total_points == 0


# ── Working through a section larger than one batch (T8.6) ──────────────────────────────

def test_a_second_batch_grades_the_next_workspaces_not_the_same_ones_again(session):
    """The bug this catches: a section of forty that can never be finished, because every press
    of Grade marks the same first batch over again."""
    from originalentry.services.grades import grade_section, ungraded_count

    ws_a, student_a, grader = _seed(session, email="b1@example.edu", join_code="b1-join")
    assignment_id = ws_a.assignment_id
    pack_version_id, variant_id = ws_a.pack_version_id, ws_a.variant_id
    others = []
    for i in range(3):
        student = User(email=f"b1-{i}@example.edu")
        session.add(student)
        session.flush()
        ws = Workspace(assignment_id=assignment_id, student_id=student.id,
                       pack_version_id=pack_version_id, variant_id=variant_id,
                       status="in_progress")
        session.add(ws)
        session.flush()
        others.append(ws)
    assignment = session.get(Assignment, assignment_id)

    first, total, cursor = grade_section(session, assignment, actor=grader, limit=2)
    second, _, cursor = grade_section(session, assignment, actor=grader, limit=2,
                                      after_id=cursor)

    assert total == 4
    assert {run.workspace_id for run in first}.isdisjoint({run.workspace_id for run in second})
    assert ungraded_count(session, assignment) == 0


def test_a_batch_run_reports_what_is_still_ungraded(session):
    from originalentry.services.grades import grade_section, ungraded_count

    ws, _, grader = _seed(session, email="b2@example.edu", join_code="b2-join")
    assignment = session.get(Assignment, ws.assignment_id)
    student = User(email="b2-second@example.edu")
    session.add(student)
    session.flush()
    session.add(Workspace(assignment_id=assignment.id, student_id=student.id,
                          pack_version_id=ws.pack_version_id, variant_id=ws.variant_id,
                          status="in_progress"))
    session.flush()

    assert ungraded_count(session, assignment) == 2
    _, _, cursor = grade_section(session, assignment, actor=grader, limit=1)
    assert ungraded_count(session, assignment) == 1
    grade_section(session, assignment, actor=grader, limit=1, after_id=cursor)
    assert ungraded_count(session, assignment) == 0
