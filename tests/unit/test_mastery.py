"""The mastery arithmetic, with no database in it.

``rank_concepts`` is the pure half of ``assignment_mastery``: marks in, ranked concepts out. The
population rules, the overrides and the scoping are integration concerns and live in
tests/integration/test_mastery_screen.py.
"""

from __future__ import annotations

from originalentry.services.grades import ComponentMark, FinalMarks
from originalentry.services.diagnostics import SignatureCount
from originalentry.services.mastery import group_mistakes, rank_concepts, top_mistake

#: component key -> (concept key, concept label), as assignment_mastery builds it from concept_tag.
TAGS = {
    "triage": ("document_triage", "Document triage"),
    "entry_accuracy": ("debit_credit", "Debit/credit and account classification"),
    "adjustment_form": ("adjusting_entries", "Adjusting entries"),
    "adjustment_amounts": ("adjusting_entries", "Adjusting entries"),
}


def _marks(*components: tuple[str, float, float]) -> FinalMarks:
    """One student's final marks, from (component key, points, max_points) triples."""
    parts = tuple(
        ComponentMark(key=key, label=key, points=points, max_points=max_points)
        for key, points, max_points in components
    )
    return FinalMarks(
        components=parts,
        total_points=sum(p.points for p in parts),
        max_points=sum(p.max_points for p in parts),
        needs_review=False,
    )


def _by_key(concepts) -> dict[str, object]:
    return {concept.key: concept for concept in concepts}


def test_pools_marks_across_students_rather_than_averaging_percentages():
    """1/10 and 18/20 is 19/30 -- 63.3% -- not the mean of 10% and 90%, which is 50%.

    Breaks if the implementation averages each student's percentage, which is the obvious wrong
    way to do it and agrees with pooling whenever every student has the same max_points.
    """
    report = rank_concepts(
        [_marks(("triage", 1, 10)), _marks(("triage", 18, 20))], TAGS)

    triage = _by_key(report)["document_triage"]
    assert (triage.points, triage.max_points) == (19, 30)
    assert round(triage.percent, 1) == 63.3


def test_two_components_of_one_concept_pool_together():
    """Adjusting entries is adjustment_form plus adjustment_amounts, so a student weak at one and
    strong at the other reads as the middle, not as two rows."""
    report = rank_concepts(
        [_marks(("adjustment_form", 2, 10), ("adjustment_amounts", 8, 10))], TAGS)

    adjusting = _by_key(report)["adjusting_entries"]
    assert (adjusting.points, adjusting.max_points) == (10, 20)
    assert len([c for c in report if c.key == "adjusting_entries"]) == 1


def test_a_concept_with_no_tagged_component_is_absent_not_zero():
    """A dormant concept -- one whose components no pack uses -- must not read as total failure."""
    report = rank_concepts([_marks(("triage", 5, 10))], TAGS)

    assert "adjusting_entries" not in _by_key(report)
    assert "debit_credit" not in _by_key(report)


def test_components_with_no_concept_pool_into_one_untagged_row_last():
    """Nothing may silently vanish from the view, so an untagged component is reported -- and it
    sorts last whatever its percentage, because it is not a concept anyone can reteach."""
    report = rank_concepts(
        [_marks(("triage", 9, 10), ("mystery_one", 0, 10), ("mystery_two", 0, 10))], TAGS)

    assert report[-1].key == "untagged"
    assert (report[-1].points, report[-1].max_points) == (0, 20)
    assert len([c for c in report if c.key == "untagged"]) == 1


def test_the_weakest_is_the_lowest_percentage_not_the_lowest_points():
    """2/100 is weaker than 1/2, though it has more points. Breaks on a sort by points."""
    report = rank_concepts(
        [_marks(("triage", 2, 100), ("entry_accuracy", 1, 2))], TAGS)

    assert report[0].key == "document_triage"


def test_no_marks_at_all_is_an_empty_report():
    """A brand-new assignment has nobody in the population; the caller shows no callout."""
    assert rank_concepts([], TAGS) == ()


def test_a_concept_with_zero_available_marks_reads_as_zero_percent_not_a_crash():
    """A pack can weight a component at zero. Division must not raise."""
    report = rank_concepts([_marks(("triage", 0, 0))], TAGS)

    assert _by_key(report)["document_triage"].percent == 0.0


# ── Block B: the mistakes, grouped ──────────────────────────────────────────────────────

def _count(key: str, students: int, possible: int = 0) -> SignatureCount:
    return SignatureCount(key=key, label=f"label for {key}", students=students, possible=possible)


SIGNATURE_TAGS = {
    "earlydisc": ("cash_discounts", "Cash discounts and discount periods"),
    "shortpay": ("cash_discounts", "Cash discounts and discount periods"),
    "freight": ("shipping_terms", "Shipping terms and freight"),
}


def test_signatures_group_under_their_concept_and_untagged_ones_are_dropped():
    """A signature with no tag is a mistake no concept can be named for, so it has no place in a
    block organised by concept. The guard in tests/guards/test_concept_tags.py is what stops that
    being a silent gap for a real pack."""
    groups = group_mistakes(
        [_count("earlydisc", 4), _count("freight", 2), _count("not_tagged_at_all", 9)],
        SIGNATURE_TAGS)

    assert [g.key for g in groups] == ["cash_discounts", "shipping_terms"]
    assert "not_tagged_at_all" not in [m.key for g in groups for m in g.mistakes]


def test_concept_groups_rank_by_their_highest_single_count_not_a_sum():
    """Summing would double-count a student who triggered two signatures of one concept. Here
    cash_discounts sums to 6 but its highest is 3, so a sum would wrongly outrank freight's 5."""
    groups = group_mistakes(
        [_count("earlydisc", 3), _count("shortpay", 3), _count("freight", 5)], SIGNATURE_TAGS)

    assert [g.key for g in groups] == ["shipping_terms", "cash_discounts"]


def test_signatures_within_a_group_are_ranked_too():
    groups = group_mistakes([_count("earlydisc", 1), _count("shortpay", 8)], SIGNATURE_TAGS)

    assert [m.key for m in groups[0].mistakes] == ["shortpay", "earlydisc"]


def test_a_signature_nobody_triggered_is_not_a_mistake_to_report():
    """cohort_diagnostics seeds every declared signature at zero, so the pack's whole catalogue
    arrives whether or not anybody made the mistake."""
    groups = group_mistakes([_count("earlydisc", 0), _count("freight", 3)], SIGNATURE_TAGS)

    assert [g.key for g in groups] == ["shipping_terms"]


def test_top_mistake_is_the_highest_count_across_every_group():
    groups = group_mistakes(
        [_count("earlydisc", 2), _count("freight", 7)], SIGNATURE_TAGS)

    assert top_mistake(groups).key == "freight"


def test_top_mistake_is_none_when_nothing_was_detected():
    assert top_mistake(group_mistakes([], SIGNATURE_TAGS)) is None
