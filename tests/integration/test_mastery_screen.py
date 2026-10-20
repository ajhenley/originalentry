"""Mastery against a real database: who is counted, and whose marks.

The arithmetic is pinned without a database in tests/unit/test_mastery.py. What needs Postgres is
everything about *which* workspaces and *which* marks: the population rule, grade overrides, and
(from Task 4) the scoping and the screen.
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
from originalentry.extensions import db
from originalentry.grading.models import DetectedSignature
from originalentry.grading.workspace import grade_workspace
from originalentry.models import (
    KIND_COMPONENT,
    KIND_SIGNATURE,
    ROLE_ADMIN,
    Assignment,
    Concept,
    ConceptTag,
    Section,
    SectionStaff,
    User,
    Variant,
    Workspace,
)
from originalentry.packs import schema
from originalentry.packs.importer import import_answer_keys, import_content
from originalentry.services.diagnostics import SignatureCount
from originalentry.services.grades import final_marks, record_run, set_override
from originalentry.services.mastery import (
    SUPPORT_THRESHOLD,
    assignment_mastery,
    concept_detail,
)
from originalentry.services.submit import submit_workspace
from sqlalchemy import select

from tests.packs import testco_alpha
from tests.scoping_world import staff_account

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
    # Graded but never handed in -- the ordinary mid-term state, since grade_section grades every
    # live workspace. Graded on purpose: if it were left ungraded too, final_marks would return
    # None for it and the exclusion would be over-determined, so an implementation pooling over
    # everyone would pass this test clean.
    _grade_without_submitting(session, workspaces[1], grader, "unused_signature", "unused")

    report = assignment_mastery(session, assignment)

    assert (report.submitted, report.total) == (1, 2)
    assert report.concepts, "the submitted workspace produced no concepts"
    # The pooled denominator is one student's worth of the pack, not two.
    one_student = final_marks(session, workspaces[0])
    triage_max = sum(c.max_points for c in one_student.components if c.key == "triage")
    pooled = {c.key: c.max_points for c in report.concepts}
    assert pooled["document_triage"] == triage_max, (
        f"pooled {pooled['document_triage']} against one student's {triage_max}: unsubmitted work "
        f"is in the denominator")


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
    """Counted over the submitted population, from the same final marks as the percentage.

    Driven UPWARD, and this matters. An untouched submitted workspace already scores zero on more
    than half of testco_alpha's hundred points -- an empty book agrees with itself, which is not
    worth marks -- so it is below the seventy-percent line before the test does anything.
    Overriding components *down* to zero, as an earlier version of this test did, changed nothing
    and the assertion held for any implementation: one that ignored overrides, one that never read
    SUPPORT_THRESHOLD, one that returned len(population).
    """
    assignment, workspaces, grader = _world(session, students=2, join_code="mastery-support")
    for workspace in workspaces:
        _submit_and_grade(session, workspace, grader)

    before = assignment_mastery(session, assignment)
    assert before.needs_support == 2, (
        "both untouched submissions should start below the line; the fixture has changed")

    # Everything to full marks, so this one is unambiguously clear of the line whatever the pack
    # weights happen to be.
    for component in final_marks(session, workspaces[0]).components:
        set_override(session, workspaces[0], component.key, points=component.max_points,
                     reason="Full marks by hand, to cross the support line", actor=grader)
    session.commit()

    after = assignment_mastery(session, assignment)
    assert after.needs_support == 1, (
        f"threshold is {SUPPORT_THRESHOLD}; one student is now at full marks and the other "
        f"untouched, so exactly one needs support, not {after.needs_support}")


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


def _grade_without_submitting(session, workspace, grader, key: str, label: str,
                              confident: bool = True):
    """Graded but never handed in, with one detected signature.

    grade_section grades every live workspace regardless of status, so this is an ordinary state
    mid-term -- and it is the state where Block A's population and Block B's diverge.
    """
    result = grade_workspace(session, workspace)
    record_run(session, workspace,
               replace(result, signatures=(DetectedSignature(key, label, confident),)),
               created_by=grader)
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


# ── The screen and the drill-down route ─────────────────────────────────────────────────

def _teaches(session, assignment, teacher):
    session.add(SectionStaff(section_id=assignment.section_id, user_id=teacher.id))
    session.commit()


def test_a_teacher_sees_mastery_for_their_own_section(client, session):
    assignment, workspaces, grader = _world(session, join_code="mastery-screen-own")
    _submit_and_grade(session, workspaces[0], grader)
    teacher = staff_account(session, "screen-own@example.edu")
    _teaches(session, assignment, teacher)
    client.sign_in(teacher)

    page = client.get(f"/staff/diagnostics/{assignment.public_id}")

    assert page.status_code == 200
    assert "Mastery by concept" in page.get_data(as_text=True)


def test_a_teacher_is_refused_another_sections_mastery(client, session):
    """404, never 403: a refusal must not confirm the assignment exists."""
    assignment, _workspaces, _grader = _world(session, join_code="mastery-screen-other")
    outsider = staff_account(session, "screen-outsider@example.edu")
    client.sign_in(outsider)

    assert client.get(f"/staff/diagnostics/{assignment.public_id}").status_code == 404
    assert client.get(
        f"/staff/diagnostics/{assignment.public_id}/concept/document_triage").status_code == 404


def test_an_admin_sees_both(client, session):
    assignment, workspaces, grader = _world(session, join_code="mastery-screen-admin")
    _submit_and_grade(session, workspaces[0], grader)
    admin = staff_account(session, "screen-admin@example.edu", role=ROLE_ADMIN)
    client.sign_in(admin)

    assert client.get(f"/staff/diagnostics/{assignment.public_id}").status_code == 200
    assert client.get(
        f"/staff/diagnostics/{assignment.public_id}/concept/document_triage").status_code == 200


def test_an_unknown_concept_key_is_a_404(client, session):
    """Review Focus 3, through the route: concept_detail raises LookupError and the view turns it
    into a 404 rather than rendering an empty page that looks valid."""
    assignment, _workspaces, _grader = _world(session, join_code="mastery-screen-404")
    admin = staff_account(session, "screen-404@example.edu", role=ROLE_ADMIN)
    client.sign_in(admin)

    assert client.get(
        f"/staff/diagnostics/{assignment.public_id}/concept/no_such_concept").status_code == 404


def test_an_assignment_with_no_tagged_component_says_so(client, session):
    """Review Focus 2. An empty Block A must explain itself, not sit silently under a callout
    naming nothing."""
    assignment, workspaces, grader = _world(session, join_code="mastery-screen-untagged")
    _submit_and_grade(session, workspaces[0], grader)
    session.execute(db.delete(ConceptTag).where(ConceptTag.artifact_kind == KIND_COMPONENT))
    session.commit()
    admin = staff_account(session, "screen-untagged@example.edu", role=ROLE_ADMIN)
    client.sign_in(admin)

    page = client.get(f"/staff/diagnostics/{assignment.public_id}").get_data(as_text=True)

    # Block A is not empty here -- every component pooled into Untagged -- so the screen has to
    # explain itself rather than offer "Review Untagged before the next assignment", which is the
    # advice it would otherwise print.
    assert "No component on this assignment carries a concept yet" in page
    assert "Review Untagged" not in page


def test_the_two_blocks_name_their_populations(client, session):
    """Block A is submitted work; Block B is everything graded. Two different questions, each
    stated, so neither contradicts the other or the CSV beside them."""
    assignment, workspaces, grader = _world(session, students=2, join_code="mastery-screen-pop")
    _submit_and_grade(session, workspaces[0], grader)
    admin = staff_account(session, "screen-pop@example.edu", role=ROLE_ADMIN)
    client.sign_in(admin)

    page = client.get(f"/staff/diagnostics/{assignment.public_id}").get_data(as_text=True)

    assert "1 of 2 submitted" in page, "Block A does not name its population"
    assert "across everyone graded" in page, "Block B does not name its population"


def test_the_drill_down_covers_the_same_population_block_b_counts(session):
    """A count you can click must list the people it counted.

    Block B comes from cohort_diagnostics, whose population is every live workspace with a run --
    deliberately broader than Block A's submitted-only, because a count does not dilute the way a
    rate does. If the drill-down narrowed to submitted work, a teacher would read "6 students",
    click, and be shown four names with nothing on either page explaining where the other two
    went. That is the spec's "figure that contradicts the screen it sits on".
    """
    assignment, workspaces, grader = _world(session, students=2, join_code="mastery-popmatch")
    _tag_signature(session, "depreciation_missed", "depreciation")
    _grade_with_signature(session, workspaces[0], grader,
                          "depreciation_missed", "Depreciation was never recorded")
    _grade_without_submitting(session, workspaces[1], grader,
                              "depreciation_missed", "Depreciation was never recorded")

    report = assignment_mastery(session, assignment)
    counted = report.mistakes[0].mistakes[0].students
    detail = concept_detail(session, assignment, "depreciation")
    listed = len(detail.mistakes[0].students)

    assert counted == 2, "Block B should count the graded-but-unsubmitted student too"
    assert listed == counted, f"Block B counted {counted}, the drill-down lists {listed}"


def test_the_drill_down_leaves_out_merely_possible_detections(session):
    """Block B counts only confident detections -- cohort_diagnostics splits them, and
    group_mistakes reads the confident tally. A drill-down that listed the balance-only
    possibilities too would show more students than the count that led to it, in the opposite
    direction from the population bug above."""
    assignment, workspaces, grader = _world(session, students=2, join_code="mastery-possible")
    _tag_signature(session, "depreciation_missed", "depreciation")
    _grade_with_signature(session, workspaces[0], grader,
                          "depreciation_missed", "Depreciation was never recorded")
    _grade_without_submitting(session, workspaces[1], grader,
                              "depreciation_missed", "Depreciation was never recorded",
                              confident=False)

    report = assignment_mastery(session, assignment)
    detail = concept_detail(session, assignment, "depreciation")

    assert report.mistakes[0].mistakes[0].students == 1, "only the confident one is counted"
    assert len(detail.mistakes[0].students) == 1, "the possible detection was listed as a fact"


def test_nothing_submitted_says_so_rather_than_blaming_the_tagging(session, client):
    """Review Focus 1, on the page rather than in the service.

    `not mastery.weakest` is true both when nothing is tagged and when nobody has submitted. The
    tagging sentence is an actionable falsehood in the second case: the teacher goes looking for a
    tagging problem that does not exist.
    """
    assignment, _workspaces, _grader = _world(session, join_code="mastery-nosub-screen")
    admin = staff_account(session, "screen-nosub@example.edu", role=ROLE_ADMIN)
    client.sign_in(admin)

    page = client.get(f"/staff/diagnostics/{assignment.public_id}").get_data(as_text=True)

    assert "Nothing has been submitted yet" in page
    assert "carries a concept yet" not in page, "blamed the tagging for an empty population"


def test_assignment_mastery_uses_the_diagnostics_it_is_given(session):
    """The view already computes cohort_diagnostics for the sections below this one. Recomputing
    it inside assignment_mastery ran a latest_run per workspace, the dispositions query, the
    activity-events query, the triage tallies and the quartiles a second time for one page -- and
    let the two blocks disagree by running against different reads.

    Falsifiable: a recomputation would find no signatures in this fixture, so freight could only
    appear if the passed-in diagnostics was used.
    """
    assignment, workspaces, grader = _world(session, join_code="mastery-given-diag")
    _submit_and_grade(session, workspaces[0], grader)
    # freight is already tagged by the seed migration -- tagging it here trips
    # uq_concept_tag_artifact, which is the constraint doing its job.
    given = SimpleNamespace(
        signatures=(SignatureCount(key="freight", label="Freight on the wrong account",
                                   students=4, possible=0),),
        graded=9, total=12)

    report = assignment_mastery(session, assignment, diagnostics=given)

    assert report.top_mistake.key == "freight"
    assert report.top_mistake.students == 4


def test_the_screen_does_not_present_a_signature_tally_as_a_rate(session, client):
    """Block B says "a count, not a rate: a misconception nobody triggered may simply never have
    been reached". The designed-errors block below it carried a column headed "Share of those
    graded", dividing the same tallies by everyone graded -- a student who enters nothing is
    graded, detect returns nothing for them, so they sit in the denominator and never the
    numerator and the rate falls as the class does less. A teacher reading top to bottom got both
    claims about the same numbers.
    """
    assignment, workspaces, grader = _world(session, join_code="mastery-no-rate")
    _submit_and_grade(session, workspaces[0], grader)
    admin = staff_account(session, "screen-norate@example.edu", role=ROLE_ADMIN)
    client.sign_in(admin)

    page = client.get(f"/staff/diagnostics/{assignment.public_id}").get_data(as_text=True)

    assert "Share of those graded" not in page
