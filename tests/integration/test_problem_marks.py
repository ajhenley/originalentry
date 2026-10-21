"""What the database has to hand the engine before the best-N rule can run.

The component itself is covered without a database in tests/unit/test_problems_best_n.py. What
needs one is the seam: `load_work` reading a real `problems_required` and real reveal rows, and
the concept tag that `KNOWN_COMPONENTS` obliges. The anti-goal is here too -- a practice set must
not acquire the new component by the mere fact of its existing.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from originalentry.extensions import db
from originalentry.grading import grade
from originalentry.grading.workspace import load_work
from originalentry.models import (
    Assignment,
    Concept,
    ConceptTag,
    ProblemAttempt,
    Section,
    User,
    Variant,
    Workspace,
)
from originalentry.packs import schema
from originalentry.packs.importer import import_answer_keys, import_content
from originalentry.packs.validate import KNOWN_COMPONENTS
from sqlalchemy import select

from tests.packs import testco_alpha
from tests.work import perfect_work

pytestmark = pytest.mark.db


@pytest.fixture
def workspace(session):
    pv = import_content(session, schema.load_pack(testco_alpha.PACK),
                        source_sha256="pmk" + "0" * 61)
    import_answer_keys(session, pv, {"A": schema.load_answer_key(testco_alpha.KEY_A)})
    variant_id = session.scalars(select(Variant.id).where(Variant.pack_version_id == pv.id)).first()
    section = Section(name="Sec", join_code="pmk-join")
    student = User(email="pmk@example.edu", given_name="Ada", family_name="Sowande")
    session.add_all([section, student])
    session.flush()
    assignment = Assignment(section_id=section.id, title="Chapter 3", company_policy="fixed",
                            fixed_pack_version_id=pv.id)
    session.add(assignment)
    session.flush()
    ws = Workspace(assignment_id=assignment.id, student_id=student.id, pack_version_id=pv.id,
                   variant_id=variant_id, status="in_progress")
    session.add(ws)
    session.flush()
    return ws


# ── the tag KNOWN_COMPONENTS obliges ───────────────────────────────────────────────────

def test_the_new_component_carries_a_concept(session):
    """tests/guards/test_concept_tags.py::test_every_component_key_is_tagged asserts
    KNOWN_COMPONENTS <= tagged, so adding a component key without its tag fails that guard
    immediately -- and leaves a permanent "Untagged" row in the mastery view."""
    assert "problems_best_n" in KNOWN_COMPONENTS

    tag = session.scalars(db.select(ConceptTag).filter_by(
        artifact_kind="component", artifact_key="problems_best_n")).one()
    concept = session.get(Concept, tag.concept_id)

    assert concept is not None, "the tag names no concept"
    assert concept.retired_at is None, "the tag names a retired concept"


def test_the_new_component_shares_entry_accuracy_s_concept(session):
    """Both ask whether a journal entry was recorded with the right accounts, sides and figures.
    If they drifted apart, the mastery view would report a student weak at one and fine at the
    other for the same misunderstanding."""
    keys = {"problems_best_n", "entry_accuracy"}
    concepts = {
        tag.artifact_key: tag.concept_id
        for tag in session.scalars(db.select(ConceptTag).where(
            ConceptTag.artifact_kind == "component",
            ConceptTag.artifact_key.in_(keys))).all()
    }

    assert set(concepts) == keys
    assert concepts["problems_best_n"] == concepts["entry_accuracy"]


# ── the seam: what load_work reads ─────────────────────────────────────────────────────

def test_load_work_carries_how_many_problems_count(session, workspace):
    """The count lives on the assignment, and the engine is pure in the work -- so somebody has to
    put it there before grade() runs."""
    session.get(Assignment, workspace.assignment_id).problems_required = 6
    session.flush()

    assert load_work(session, workspace).problems_required == 6


def test_load_work_carries_no_count_for_a_practice_set(session, workspace):
    """Null on every practice set, and the components that divide their points must keep seeing
    None rather than a number somebody invented."""
    assert load_work(session, workspace).problems_required is None


def test_load_work_reads_the_reveals_from_the_database(session, workspace):
    """Server-side state: what the student was shown is a row, not something a page carried."""
    session.add(ProblemAttempt(workspace_id=workspace.id, document_ref="P-01", attempts=2,
                               answer_shown_at=datetime.now(UTC)))
    session.add(ProblemAttempt(workspace_id=workspace.id, document_ref="P-02", attempts=4))
    session.flush()

    revealed = load_work(session, workspace).revealed

    assert revealed == {"P-01"}, "an attempted-but-unrevealed problem was treated as revealed"


def test_an_attempt_row_alone_does_not_make_a_problem_revealed(session, workspace):
    """Guards the test above from the inside: if `revealed` read every row, a student who merely
    practised would lose the mark."""
    session.add(ProblemAttempt(workspace_id=workspace.id, document_ref="P-03", attempts=9))
    session.flush()

    assert load_work(session, workspace).revealed == frozenset()


def test_one_student_s_reveals_do_not_reach_another_s_work(session, workspace):
    """The rows are keyed by workspace, and a leak here would cost a classmate their marks."""
    other_student = User(email="pmk2@example.edu", given_name="Bo", family_name="Adeyemi")
    session.add(other_student)
    session.flush()
    other = Workspace(assignment_id=workspace.assignment_id, student_id=other_student.id,
                      pack_version_id=workspace.pack_version_id,
                      variant_id=workspace.variant_id, status="in_progress")
    session.add(other)
    session.flush()
    session.add(ProblemAttempt(workspace_id=other.id, document_ref="P-01", attempts=1,
                               answer_shown_at=datetime.now(UTC)))
    session.flush()

    assert load_work(session, workspace).revealed == frozenset()
    assert load_work(session, other).revealed == {"P-01"}


# ── the anti-goal ──────────────────────────────────────────────────────────────────────

def test_a_practice_set_never_runs_the_new_component(session, workspace):
    """The anti-goal, executable. A pack's rubric decides which components run, and no practice
    set's rubric names this one -- so its marks cannot move by a point."""
    pack = schema.load_pack(testco_alpha.PACK)
    key = schema.load_answer_key(testco_alpha.KEY_A)

    result = grade(perfect_work(pack, key), pack, key)

    assert "problems_best_n" not in {component.key for component in result.components}


def test_a_practice_set_still_earns_every_point_it_did(session, workspace):
    """The other half: adding two defaulted fields to StudentWork must not disturb a single
    existing component."""
    pack = schema.load_pack(testco_alpha.PACK)
    key = schema.load_answer_key(testco_alpha.KEY_A)

    result = grade(perfect_work(pack, key), pack, key)

    for component in result.components:
        assert component.points == pytest.approx(component.max_points), component.key
    assert not result.needs_review
