"""A ref is a position, not an identity, and a migration that trusts it reattaches work.

Alder & Finch v1 to v2: of 17 refs shared between the versions, 8 named a different artefact and
2 flipped their triage answer -- D03 went from a vendor invoice, which takes an entry, to a
purchase order, which takes none. The migration would have reported fully feasible, because the
gate asks whether content has disappeared, not whether a surviving ref now means something else.

This is the comparison that answers the second question. It is pure so it can be tested without a
database and reused by both the guard and the operator's report.
"""

from __future__ import annotations

from originalentry.packs.version_diff import IdentityChange, identity_changes


def _docs(**refs):
    return {ref: dict(display_ref=d, doc_type="source_document") for ref, d in refs.items()}


def test_a_ref_that_names_a_different_document_is_reported():
    changes = identity_changes(
        _docs(D01="Invoice 4871"), _docs(D01="Purchase order RB-1180"), {}, {}
    )

    assert changes == [
        IdentityChange("D01", "display_ref", "Invoice 4871", "Purchase order RB-1180")
    ]


def test_an_unchanged_ref_is_not_reported():
    assert identity_changes(_docs(D01="Invoice 4871"), _docs(D01="Invoice 4871"), {}, {}) == []


def test_a_ref_only_one_side_has_is_not_compared():
    """Added and removed refs are real, but they are not identity changes and the existing
    missing_documents check already covers what a student used and lost."""
    assert identity_changes(_docs(D01="A"), _docs(D02="B"), {}, {}) == []


def test_a_changed_doc_type_is_reported():
    old = {"D01": dict(display_ref="Tape", doc_type="source_document")}
    new = {"D01": dict(display_ref="Tape", doc_type="summary")}

    assert identity_changes(old, new, {}, {}) == [
        IdentityChange("D01", "doc_type", "source_document", "summary")
    ]


def test_a_changed_kind_is_reported_and_a_missing_one_is_not():
    """kind arrived with the printed-envelope packs, so a pack that predates it has none. An
    absent kind on either side is not a change -- treating it as one would report every document
    of every older pack."""
    old = {"D01": dict(display_ref="X", doc_type="t", kind="sales_invoice")}
    new = {"D01": dict(display_ref="X", doc_type="t", kind="purchase_order")}
    bare = {"D01": dict(display_ref="X", doc_type="t")}

    assert identity_changes(old, new, {}, {}) == [
        IdentityChange("D01", "kind", "sales_invoice", "purchase_order")
    ]
    assert identity_changes(bare, old, {}, {}) == []
    assert identity_changes(old, bare, {}, {}) == []


def test_a_flipped_triage_answer_is_reported_per_variant():
    """The sharpest case: a document a student correctly journalised becomes one that needs no
    entry, so correct work reads as wrong."""
    docs = _docs(D03="Vendor inv CV-3310")

    changes = identity_changes(
        docs,
        docs,
        {"A": {"D03": True}, "B": {"D03": True}},
        {"A": {"D03": False}, "B": {"D03": True}},
    )

    assert changes == [IdentityChange("D03", "triage", "A: needs an entry", "A: needs none")]


def test_triage_is_only_compared_where_both_versions_answer_it():
    docs = _docs(D01="X")

    assert identity_changes(docs, docs, {"A": {}}, {"A": {"D01": True}}) == []
    assert identity_changes(docs, docs, {"A": {"D01": True}}, {"B": {"D01": False}}) == []


def test_the_result_is_sorted_so_two_runs_read_the_same():
    old = {"D02": dict(display_ref="a", doc_type="t"), "D01": dict(display_ref="a", doc_type="t")}
    new = {"D02": dict(display_ref="b", doc_type="u"), "D01": dict(display_ref="b", doc_type="t")}

    assert [(c.ref, c.field) for c in identity_changes(old, new, {}, {})] == [
        ("D01", "display_ref"), ("D02", "display_ref"), ("D02", "doc_type")
    ]
