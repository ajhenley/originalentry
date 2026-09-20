"""Cohort diagnostics (I4.1–I4.3, I4.5).

This is the screen the paper set could never provide: which designed errors a section actually
made, which documents were most often handled differently from the key, and how long the work
took. It reports facts about the cohort and names no student as having done anything wrong.
"""

import copy

import pytest
from originalentry.grading.workspace import grade_workspace
from originalentry.services.diagnostics import cohort_csv, cohort_diagnostics
from originalentry.services.grades import record_run

from tests.packs import testco_alpha
from tests.perfect_student import build

pytestmark = pytest.mark.db


def _expensed_the_sale(key_dict):
    """A student who put a sale in an expense account: the pack's first designed error."""
    worked = copy.deepcopy(key_dict)
    entry = next(e for e in worked["expected_entries"] if e["document"] == "INV-2")
    for line in entry["lines"]:
        if line["account"] == "401":
            line["account"] = "611"
            line["debit"] = line.pop("credit")
    return worked


@pytest.fixture
def section(session):
    """Two students on one assignment: one followed the key, one made a designed error."""
    good = build(session, testco_alpha.PACK, testco_alpha.KEY_A,
                 email="diag-good@example.edu", join_code="diag1")
    workspace, student, pack, key = good
    assignment_id = workspace.assignment_id

    from originalentry.models import Assignment, User, Variant, Workspace
    from sqlalchemy import select

    assignment = session.get(Assignment, assignment_id)
    variant_id = session.scalars(
        select(Variant.id).where(Variant.pack_version_id == workspace.pack_version_id)
    ).first()
    other_student = User(email="diag-slip@example.edu", given_name="Ola", family_name="Okoro")
    session.add(other_student)
    session.flush()
    other = Workspace(assignment_id=assignment.id, student_id=other_student.id,
                      pack_version_id=workspace.pack_version_id, variant_id=variant_id,
                      status="in_progress")
    session.add(other)
    session.flush()

    # The second student's work, built from a key carrying the designed error.
    from originalentry.packs import schema

    from tests.perfect_student import _adjust, _close, _journalise, _post_everything, _triage

    worked = schema.load_answer_key(_expensed_the_sale(testco_alpha.KEY_A))
    _triage(session, other, other_student, worked)
    _journalise(session, other, other_student, pack, worked)
    _adjust(session, other, other_student, pack, worked)
    _post_everything(session, other, other_student, pack)
    _close(session, other, other_student, pack, worked)
    _post_everything(session, other, other_student, pack)

    for ws in (workspace, other):
        record_run(session, ws, grade_workspace(session, ws))
    return assignment, workspace, other


def test_the_screen_counts_who_made_each_designed_error(session, section):
    assignment, _, _ = section

    diagnostics = cohort_diagnostics(session, assignment)

    assert diagnostics.graded == 2
    by_key = {row.key: row for row in diagnostics.signatures}
    assert by_key["sale_to_an_expense_account"].students == 1
    assert by_key["sale_to_an_expense_account"].label == "Recorded a sale in an expense account"
    assert by_key["invoice_overstated"].students == 0


def test_documents_handled_differently_from_the_key_are_counted(session, section):
    assignment, _, other = section
    from originalentry.models import User
    from originalentry.services import workspace_write
    from originalentry.services.dispositions import set_disposition

    student = session.get(User, other.student_id)
    workspace_write(session, other.public_id, student, activity_kind="disposition",
                    mutate=lambda s, w: set_disposition(s, w, "INV-1", "no_entry", "seemed a copy"))

    diagnostics = cohort_diagnostics(session, assignment)

    miss = next(row for row in diagnostics.triage if row.document_ref == "INV-1")
    assert miss.no_entry_when_one_is_expected == 1
    assert miss.recorded_when_none_is_expected == 0


def test_time_on_task_is_reported_for_the_cohort(session, section):
    assignment, _, _ = section

    diagnostics = cohort_diagnostics(session, assignment)

    assert diagnostics.time_on_task.students == 2
    assert diagnostics.time_on_task.median_minutes >= 0


def test_the_cohort_exports_as_one_row_per_student(session, section):
    assignment, _, _ = section

    rows = list(cohort_csv(session, assignment))

    header, *body = rows
    assert header[:4] == ["email", "family_name", "given_name", "variant"]
    assert "total_points" in header and "time_on_task_minutes" in header
    assert len(body) == 2
    assert {row[0] for row in body} == {"diag-good@example.edu", "diag-slip@example.edu"}
