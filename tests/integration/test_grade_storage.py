"""Storing what the engine decided (T8.1, I3.2–I3.5, A12).

A grade run is immutable: regrading adds a run, it never edits one. An override is a separate
record with a reason, and it survives a regrade — otherwise an instructor's judgement would be
undone by the next run of the engine, which is exactly the bug A12 exists to catch.
"""

import pytest
from parchment.grading.workspace import grade_workspace
from parchment.models import Assignment, GradeRun, Section, User, Variant, Workspace
from parchment.packs import schema
from parchment.packs.importer import import_answer_keys, import_content
from parchment.services import workspace_write
from parchment.services.dispositions import set_disposition
from parchment.services.grades import (
    final_marks,
    from_hundredths,
    latest_run,
    record_run,
    set_comment,
    set_override,
)
from parchment.services.submit import submit_workspace
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
