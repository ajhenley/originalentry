"""A9 through the database (Part III §6.3, §7.2).

The same student as A3, with one difference: INV-2 goes in the General Journal and is credited to
capital instead of sales. Everything after that is handled properly on the books that mistake left
behind — posted, adjusted, closed, and laid out in a statement carrying their own figures.

The mistake costs marks where it was made. Nowhere else.
"""

import copy

import pytest
from parchment.grading.workspace import grade_workspace

from tests.packs import testco_alpha
from tests.perfect_student import build

pytestmark = pytest.mark.db


@pytest.fixture
def mis_journalised(session):
    worked_from = copy.deepcopy(testco_alpha.KEY_A)
    entry = next(e for e in worked_from["expected_entries"] if e["document"] == "INV-2")
    entry["journal"] = "general"
    for line in entry["lines"]:
        if line["account"] == "401":
            line["account"] = "301"
    return build(session, testco_alpha.PACK, testco_alpha.KEY_A,
                 email="a9db@example.edu", join_code="a9db", worked_from=worked_from)


def test_a9_one_mistake_handled_properly_afterwards_still_scores_well(session, mis_journalised):
    workspace, _, _, _ = mis_journalised

    result = grade_workspace(session, workspace)

    assert result.total_points / result.max_points >= 0.85


def test_the_marks_come_off_where_the_mistake_was_made(session, mis_journalised):
    workspace, _, _, _ = mis_journalised

    result = grade_workspace(session, workspace)

    selection = result.component("journal_selection")
    assert selection.points == pytest.approx(selection.max_points / 2)
    assert result.component("entry_accuracy").points < result.component("entry_accuracy").max_points
    for untouched in ("triage", "posting_completeness", "subsidiary_agreement",
                      "adjustment_form", "adjustment_amounts", "closing",
                      "statements_structure", "statements_figures"):
        component = result.component(untouched)
        assert component.points == pytest.approx(component.max_points), untouched
