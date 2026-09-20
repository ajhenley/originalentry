"""A3 through the database (Part III §6.1, §7.2).

The in-memory golden tests prove the marking rules. This one proves the path: a student who did
everything the way the key does, built through the same services a browser drives, scores full
marks when grading reads their work back out of Postgres.

It exists because a loader bug — entries carrying no document reference — passed every in-memory
test while scoring a real workspace zero on triage, journal selection and entry accuracy.
"""

import pytest
from originalentry.grading.workspace import grade_workspace
from originalentry.services.grades import final_marks, record_run

from tests.packs import testco_alpha
from tests.perfect_student import build

pytestmark = pytest.mark.db


@pytest.fixture
def perfect(session):
    return build(session, testco_alpha.PACK, testco_alpha.KEY_A,
                 email="perfect@example.edu", join_code="a3db")


def test_a3_a_student_who_followed_the_key_scores_full_marks_from_the_database(session, perfect):
    workspace, _, _, _ = perfect

    result = grade_workspace(session, workspace)

    for component in result.components:
        assert component.points == pytest.approx(component.max_points), (
            f"{component.key}: " + "; ".join(f"{row.item}: {row.detail}" for row in
                                             component.evidence if row.earned < row.possible)
        )
    assert result.total_points == pytest.approx(result.max_points)


def test_nothing_about_that_work_looks_like_a_designed_error(session, perfect):
    workspace, _, _, _ = perfect

    result = grade_workspace(session, workspace)

    assert result.signatures == ()
    assert result.unexplained == ()
    assert not result.needs_review


def test_the_stored_run_says_the_same_thing(session, perfect):
    workspace, _, _, _ = perfect

    record_run(session, workspace, grade_workspace(session, workspace))

    marks = final_marks(session, workspace)
    assert marks.total_points == pytest.approx(marks.max_points)
    assert marks.percent == pytest.approx(100.0)
