"""Mastery against a real database: who is counted, and whose marks.

The arithmetic is pinned without a database in tests/unit/test_mastery.py. What needs Postgres is
everything about *which* workspaces and *which* marks: the population rule, grade overrides, and
(from Task 4) the scoping and the screen.
"""

from __future__ import annotations

import pytest
from dataclasses import replace

from originalentry.extensions import db
from originalentry.grading.models import DetectedSignature
from originalentry.grading.workspace import grade_workspace
from originalentry.models import (
    KIND_SIGNATURE,
    Assignment,
    Concept,
    ConceptTag,
    Section,
    User,
    Variant,
    Workspace,
)
from originalentry.packs import schema
from originalentry.packs.importer import import_answer_keys, import_content
from originalentry.services.grades import record_run, set_override
from originalentry.services.mastery import (
    SUPPORT_THRESHOLD,
    assignment_mastery,
    concept_detail,
)
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


# ── Block B and the drill-down ──────────────────────────────────────────────────────────

def _tag_signature(session, signature_key: str, concept_key: str) -> None:
    """Tag a fixture pack's signature onto a seeded concept.

    testco_alpha declares its own signatures, which the production seed deliberately does not tag
    -- the seed covers the thirteen keys real packs declare. Tagging one here is test setup, not a
    gap in the seed, and tests/guards/test_concept_tags.py only walks packs/*/source.json so it
    does not demand fixture signatures be tagged.
    """
    concept = session.scalars(db.select(Concept).filter_by(key=concept_key)).one()
    session.add(ConceptTag(concept_id=concept.id, artifact_kind=KIND_SIGNATURE,
                           artifact_key=signature_key))
    session.commit()


def _grade_with_signature(session, workspace, grader, key: str, label: str):
    """Submit and grade, then record a run carrying one detected signature.

    Doctoring the result is the honest way to test the grouping: making the student commit the
    exact wrong entry a detector watches for would test the detector, which grading/ already has
    its own tests for.
    """
    submit_workspace(session, workspace)
    result = grade_workspace(session, workspace)
    record_run(session, workspace,
               replace(result, signatures=(DetectedSignature(key, label, True),)),
               created_by=grader)
    session.commit()


def test_the_mistakes_block_groups_detected_signatures_under_their_concept(session):
    assignment, workspaces, grader = _world(session, join_code="mastery-mistakes")
    _tag_signature(session, "depreciation_missed", "depreciation")
    _grade_with_signature(session, workspaces[0], grader,
                          "depreciation_missed", "Depreciation was never recorded")

    report = assignment_mastery(session, assignment)

    assert [g.key for g in report.mistakes] == ["depreciation"]
    assert [m.key for m in report.mistakes[0].mistakes] == ["depreciation_missed"]
    assert report.mistakes[0].mistakes[0].students == 1
    assert report.top_mistake.key == "depreciation_missed"


def test_concept_detail_for_a_process_concept_lists_students_lowest_first(session):
    assignment, workspaces, grader = _world(session, students=2, join_code="mastery-detail-proc")
    for workspace in workspaces:
        _submit_and_grade(session, workspace, grader)
    set_override(session, workspaces[1], "triage", points=9.0,
                 reason="One student ahead of the other", actor=grader)
    session.commit()

    detail = concept_detail(session, assignment, "document_triage")

    assert detail.group == "process"
    assert [m.points for m in detail.marks] == [0.0, 9.0], "not sorted lowest first"
    assert detail.mistakes == () and detail.clear == ()


def test_concept_detail_for_a_topic_concept_groups_students_under_each_signature(session):
    assignment, workspaces, grader = _world(session, students=2, join_code="mastery-detail-topic")
    _tag_signature(session, "depreciation_missed", "depreciation")
    _grade_with_signature(session, workspaces[0], grader,
                          "depreciation_missed", "Depreciation was never recorded")
    _submit_and_grade(session, workspaces[1], grader)   # nothing detected for this one

    detail = concept_detail(session, assignment, "depreciation")

    assert detail.group == "topic"
    assert detail.marks == (), "a topic concept has no marks of its own"
    assert [s.signature_key for s in detail.mistakes] == ["depreciation_missed"]
    assert len(detail.mistakes[0].students) == 1


def test_concept_detail_lists_students_with_nothing_detected_separately(session):
    """Absence of a signature is not evidence of understanding -- detection bails entirely on
    empty books -- so they are listed, never counted as mastery."""
    assignment, workspaces, grader = _world(session, students=2, join_code="mastery-detail-clear")
    _tag_signature(session, "depreciation_missed", "depreciation")
    _grade_with_signature(session, workspaces[0], grader,
                          "depreciation_missed", "Depreciation was never recorded")
    _submit_and_grade(session, workspaces[1], grader)

    detail = concept_detail(session, assignment, "depreciation")

    assert len(detail.clear) == 1
    triggered = {s.workspace_public_id for s in detail.mistakes[0].students}
    assert {s.workspace_public_id for s in detail.clear} & triggered == set()


def test_concept_detail_raises_for_an_unknown_concept(session):
    """Review Focus 3. The view turns LookupError into abort(404) rather than rendering an empty
    page that looks valid."""
    assignment, _workspaces, _grader = _world(session, join_code="mastery-detail-404")

    with pytest.raises(LookupError):
        concept_detail(session, assignment, "no_such_concept")


def test_concept_detail_raises_for_a_retired_concept(session):
    assignment, _workspaces, _grader = _world(session, join_code="mastery-detail-retired")
    concept = session.scalars(db.select(Concept).filter_by(key="closing")).one()
    concept.retired_at = db.func.now()
    session.commit()

    with pytest.raises(LookupError):
        concept_detail(session, assignment, "closing")


def test_a_choice_assignment_does_not_raise(session):
    """Review Focus 5. fixed_pack_version_id is None and diagnostics._keys_by_variant returns {},
    so the mistakes block has no catalogue to seed from."""
    assignment, workspaces, grader = _world(session, join_code="mastery-choice")
    assignment.company_policy = "choice"
    assignment.fixed_pack_version_id = None
    session.commit()
    _submit_and_grade(session, workspaces[0], grader)

    report = assignment_mastery(session, assignment)

    assert report.submitted == 1
    assert report.concepts, "process mastery should still pool: component keys are global"
