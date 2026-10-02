"""Reading a printed artefact's own words off its own html.

``build_pack.py``'s ``_text_from_html`` is what turns the envelope's markup into the
``text_alternative`` a student hears when they cannot use the photograph. The money invariant in
``test_document_manifest.py`` covers its *figures* very well — in both directions, over all 26
documents and all three versions — and covers neither label/value pairing nor whitespace. Two
one-line changes to behaviours the code explicitly documents passed that module 15/15, the worse
of them orphaning "Sold to" from the customer it is above on every one of the 26 artefacts.

So: one crafted fragment per documented behaviour. This needs no practicesets checkout and no
renderer, so it runs everywhere the suite runs — including the CI that has neither.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def read():
    """``scripts`` is not a package, so the module is loaded by path."""
    spec = importlib.util.spec_from_file_location(
        "build_pack", ROOT / "scripts" / "build_pack.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._text_from_html


def test_a_label_and_its_value_on_two_lines_are_one_field(read):
    """``_Reading.line_break``: "A label and its value are routinely on two lines (Received from
    above the customer's address)." A <br> therefore ends a line *unless* a label is still
    waiting for its value.

    This is the one that is not cosmetic. Every "Sold to", "Received from", "Pay to", "Consignee"
    and "Charge to" on all 26 artefacts is written this way, and closing on the <br> turns the
    customer into three anonymous lines with the label stranded above them.
    """
    out = read('<div><span class="lbl">Sold to</span><br>Marisol Okonkwo'
               '<br>18 Larkspur Lane, Kettle Springs</div>')

    assert out["fields"] == [
        ["Sold to", "Marisol Okonkwo 18 Larkspur Lane, Kettle Springs"]]


def test_a_non_breaking_space_is_a_space(read):
    """``_collapse``: "A non-breaking space is a space to a reader." The sheets use &nbsp; to
    hold figures off their labels, and a reader should hear one space, not a character."""
    out = read("<div>Amount&nbsp;&nbsp;42.00</div>")

    assert out["fields"] == [["", "Amount 42.00"]]
    assert "\xa0" not in out["fields"][0][1]


def test_one_space_between_words_and_none_at_the_ends(read):
    """``_collapse``: the markup is written for a printer, so it carries the newlines and runs of
    indentation of the generator that emitted it."""
    out = read("<div>\n    Charge to:    Office Salaries Expense\n  </div>")

    assert out["fields"] == [["", "Charge to: Office Salaries Expense"]]


def test_an_unclosed_cell_does_not_swallow_the_rest_of_the_document(read):
    """``_Markup.handle_endtag``: "The paper set writes unclosed <td> and <tr> in places, so this
    is not hypothetical." An element left open is closed by its parent's end tag, which is what a
    browser does with the same markup — so the second cell is its own line, not part of the
    first."""
    out = read('<table class="meta"><tr><td>No. 7101<td>Date Dec 1</table>')

    assert out["fields"] == [["", "No. 7101"], ["", "Date Dec 1"]]


def test_an_end_tag_nothing_opened_is_ignored(read):
    """The other half of the same guard. A stray </span> must not close the block it is inside
    and leave the rest of the artefact reading as one run."""
    out = read("<div>Total 42.00</span></p></div><div>Thank you</div>")

    assert out["fields"] == [["", "Total 42.00"], ["", "Thank you"]]


def test_a_label_with_nothing_after_it_is_a_line_of_its_own(read):
    """``_Reading.end_block``: "A label with nothing after it is not a label; it is a line of its
    own, like the CUSTOMER COPY stamped on an invoice." It must not be dropped, and it must not
    swallow whatever block comes next as its value."""
    out = read('<div><span class="lbl">CUSTOMER COPY</span></div><div>Page 1 of 1</div>')

    assert out["fields"] == [["", "CUSTOMER COPY"], ["", "Page 1 of 1"]]


def test_a_label_interrupted_by_the_next_label_keeps_its_own_line(read):
    """``_Reading.label``: a second span.lbl arriving before the first one's value emits the
    first as a bare line. A voucher's "Approved J.F. Received by S.M." signature block is
    written this way."""
    out = read('<div><span class="lbl">Approved</span>'
               '<span class="lbl">Received by</span> S.M.</div>')

    assert out["fields"] == [["", "Approved"], ["Received by", "S.M."]]


def test_text_carrying_no_label_is_still_read(read):
    """``_Reading``: "Text carrying no label of its own is still a field, with an empty label,
    because dropping it would lose the company's name, a cheque's Pay to the order of, and a
    register tape's total." Nine artefacts belong to no transaction and this is most of what
    they say."""
    out = read("<div>ALDER &amp; FINCH VETERINARY CLINIC</div>"
               "<div>CASH REGISTER TAPE &middot; Dec 4</div><div>TOTAL 1,205.00</div>")

    assert out["fields"] == [["", "ALDER & FINCH VETERINARY CLINIC"],
                             ["", "CASH REGISTER TAPE · Dec 4"],
                             ["", "TOTAL 1,205.00"]]


def test_words_inside_an_inline_element_join_the_words_around_them(read):
    """``_read``: an inline tag's words join their neighbours; everything else begins and ends a
    line. The sheets set account numbers in <b> and emphasis in <em> mid-sentence."""
    out = read("<div>Charge to: <b>512</b> Office <em>Salaries</em> Expense</div>")

    assert out["fields"] == [["", "Charge to: 512 Office Salaries Expense"]]


def test_the_line_item_table_is_read_as_rows_with_its_heading(read):
    """``_rows``: "the heading row included: a column of figures with no heading is not something
    a screen reader can make sense of". ``_flat`` flattens a <br> inside a cell to a space, and a
    row with nothing in any cell is dropped rather than read as empty."""
    out = read('<table class="items">'
               '<tr><th>Item</th><th class="r">Amount</th></tr>'
               '<tr><td>Exam<br>fee</td><td class="r">90.00</td></tr>'
               '<tr><td></td><td></td></tr>'
               "</table>")

    assert out["lines"] == [["Item", "Amount"], ["Exam fee", "90.00"]]
    assert out["fields"] == []


def test_a_layout_table_is_lines_and_only_an_items_table_is_line_items(read):
    """``_read`` keys on ``table.items``: the sheets use ``table.meta`` for the address block and
    ``table.items`` for the goods. Reading the address block as line items would put the
    customer's street into the figures table."""
    out = read('<table class="meta"><tr><td><span class="lbl">Sold to</span><br>Okonkwo</td>'
               "<td>Date Dec 1</td></tr></table>"
               '<table class="items"><tr><th>Memo</th></tr>'
               "<tr><td>December power</td></tr></table>")

    assert out["fields"] == [["Sold to", "Okonkwo"], ["", "Date Dec 1"]]
    assert out["lines"] == [["Memo"], ["December power"]]


def test_the_characters_a_student_reads_are_characters(read):
    """``_Markup``: "``convert_charrefs`` is the default and is wanted: &middot; and &mdash; are
    characters a student reads." The footer that names the version is written with both."""
    out = read("<div>Alder &amp; Finch &middot; invoice 7101 &mdash; version B</div>")

    assert out["fields"] == [["", "Alder & Finch · invoice 7101 — version B"]]
