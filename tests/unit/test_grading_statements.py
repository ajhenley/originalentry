"""Grading the statements the student built (T8.2, tension 7).

Structure and figures are marked apart, so a student whose layout is sound keeps those marks even
when an earlier slip carried a wrong figure into every line. Figures are checked against the
student's **own** balances, never the key's.
"""

import pytest
from parchment.grading import grade
from parchment.grading.models import StatementRow
from parchment.packs import schema

from tests.packs import testco_alpha
from tests.work import MODEL_INCOME_STATEMENT, perfect_work


@pytest.fixture(scope="module")
def pack():
    return schema.load_pack(testco_alpha.PACK)


@pytest.fixture(scope="module")
def key():
    return schema.load_answer_key(testco_alpha.KEY_A)


def _work(pack, key, **changes):
    return perfect_work(pack, key, **changes)


def test_a_statement_built_from_their_own_books_earns_both_components(pack, key):
    result = grade(_work(pack, key), pack, key)

    for component_key in ("statements_structure", "statements_figures"):
        component = result.component(component_key)
        assert component.points == pytest.approx(component.max_points), component_key


def test_a_statement_never_started_earns_nothing_and_says_so(pack, key):
    result = grade(_work(pack, key, statements={}), pack, key)

    structure = result.component("statements_structure")
    assert structure.points == 0
    assert any("not started" in row.detail.lower() for row in structure.evidence)


def test_an_account_from_another_section_keeps_the_rest_of_the_structure_marks(pack, key):
    rows = (
        StatementRow(kind="account", account_number="401", amount_cents=200000),
        StatementRow(kind="account", account_number="101", amount_cents=500000),  # an asset
        StatementRow(kind="subtotal", subtotal_type="net_income", amount_cents=175000),
    )

    result = grade(_work(pack, key, statements={"income_statement": rows}), pack, key)

    structure = result.component("statements_structure")
    assert 0 < structure.points < structure.max_points
    assert structure.needs_review
    assert any("101" in reason for reason in structure.review_reasons)


def test_a_missing_required_subtotal_costs_only_that_check(pack, key):
    rows = tuple(r for r in MODEL_INCOME_STATEMENT if r.kind != "subtotal")

    structure = grade(
        _work(pack, key, statements={"income_statement": rows}), pack, key
    ).component("statements_structure")

    assert 0 < structure.points < structure.max_points
    assert any("Net income" in row.item for row in structure.evidence)


def test_figures_are_marked_against_the_students_own_balances(pack, key):
    rows = (
        StatementRow(kind="account", account_number="401", amount_cents=999999),  # not their own
        StatementRow(kind="account", account_number="611", amount_cents=25000),
        StatementRow(kind="subtotal", subtotal_type="net_income", amount_cents=175000),
    )

    figures = grade(
        _work(pack, key, statements={"income_statement": rows}), pack, key
    ).component("statements_figures")

    assert 0 < figures.points < figures.max_points
    assert any("401" in row.item and row.earned == 0 for row in figures.evidence)


def test_a_layout_that_is_sound_keeps_its_structure_marks_when_every_figure_is_carried_wrong(
    pack, key
):
    """The method-not-match rule: structure survives a figure that came from an earlier slip."""
    rows = tuple(
        row if row.kind != "account"
        else StatementRow(kind="account", account_number=row.account_number,
                          amount_cents=(row.amount_cents or 0) + 1000, indent=row.indent)
        for row in MODEL_INCOME_STATEMENT
    )

    result = grade(_work(pack, key, statements={"income_statement": rows}), pack, key)

    structure = result.component("statements_structure")
    assert structure.points == pytest.approx(structure.max_points)
    assert result.component("statements_figures").points < result.component(
        "statements_figures"
    ).max_points


def test_the_stage_a_statement_reads_comes_from_the_pack(pack, key):
    """A post-closing statement is checked against post-closing balances, not adjusted ones."""
    post_closing_pack = schema.load_pack(
        {
            **testco_alpha.PACK,
            "statements": [
                *testco_alpha.PACK["statements"],
                {"type": "post_closing_trial_balance", "title": "Post-closing trial balance",
                 "stage": "post_closing", "allowed_sections": ["current_assets"],
                 "subtotal_types": [], "required_subtotals": []},
            ],
        }
    )
    rows = (StatementRow(kind="account", account_number="101", amount_cents=500000),)

    figures = grade(
        _work(pack, key, statements={"post_closing_trial_balance": rows}),
        post_closing_pack,
        key,
    ).component("statements_figures")

    assert any("101" in row.item and row.earned == row.possible for row in figures.evidence)
