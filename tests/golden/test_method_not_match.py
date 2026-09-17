"""The two tests that protect the design (A3, A9, Part III §7.2).

**A3** — work that follows the key earns every mark.

**A9** — a student who mis-journalises one document and then handles everything afterwards
properly **on their own figures** still scores well. The mistake costs marks where it was made,
and nowhere else. Every future change to grading has to keep this passing; it is the difference
between marking method and marking the match.
"""

import copy

import pytest
from parchment.grading import grade
from parchment.packs import replay, schema

from tests.packs import testco_alpha
from tests.work import perfect_work, statement_rows_from_own_balances


@pytest.fixture(scope="module")
def pack():
    return schema.load_pack(testco_alpha.PACK)


@pytest.fixture(scope="module")
def key():
    return schema.load_answer_key(testco_alpha.KEY_A)


def test_a3_work_that_follows_the_key_earns_full_marks(pack, key):
    result = grade(perfect_work(pack, key), pack, key)

    assert result.total_points == pytest.approx(result.max_points)
    assert result.max_points == 100
    assert result.signatures == ()


def test_a9_one_mis_journalised_document_followed_properly_still_scores_well(pack, key):
    """INV-2 goes in the General Journal, credited to capital instead of sales.

    Everything after that is done properly on the books the student now has: posted, adjusted,
    closed, and laid out in a statement that carries their own figures.
    """
    mistaken = copy.deepcopy(testco_alpha.KEY_A)
    entry = next(e for e in mistaken["expected_entries"] if e["document"] == "INV-2")
    entry["journal"] = "general"
    for line in entry["lines"]:
        if line["account"] == "401":
            line["account"] = "301"
    snapshot = replay.build_replay_snapshot(pack, schema.load_answer_key(mistaken))

    work = perfect_work(
        pack, key, snapshot=snapshot,
        statements={"income_statement": statement_rows_from_own_balances(snapshot, pack)},
    )
    result = grade(work, pack, key)

    assert result.total_points / result.max_points >= 0.85

    # The marks come off where the mistake was made, and nowhere else.
    assert result.component("journal_selection").points == pytest.approx(
        result.component("journal_selection").max_points / 2
    )
    assert result.component("entry_accuracy").points < result.component("entry_accuracy").max_points
    for untouched in ("triage", "posting_completeness", "subsidiary_agreement",
                      "adjustment_form", "adjustment_amounts", "closing",
                      "statements_structure", "statements_figures"):
        component = result.component(untouched)
        assert component.points == pytest.approx(component.max_points), untouched
