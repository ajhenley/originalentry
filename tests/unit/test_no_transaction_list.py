"""The product's claim, kept: there is no transaction list.

README.md and CASES.md both say it in bold. The online pack said otherwise, one line per
document: every Riverbend document carried a "Description" row holding the model's own
description of the transaction, and for five of them that row stated the designed error the
student was supposed to find for themselves.

The row-removal assertion below is Riverbend-only. It was originally written over both packs on
the theory that the row had two sources — the builder wrote 84 of the 93 document/variant pairs
from txn["desc"] and the profile authored the other 9 — but neither source is the clinic's: its
text is scraped verbatim from the printed envelope's own html (see build_pack.py's `_Reading`),
never built from txn["desc"]. The word "Description" does appear in the clinic's data, but only
as a `<th>Description</th>` column heading on an item table (../practicesets/generators/gendocs.py
uses this heading for every company), which the html parser routes into `lines`, not `fields` —
required table structure, not a leaked sentence. Scanning `lines` for the literal word would only
flag that heading on every itemised document, which is not what this test polices.

Whether the clinic has some OTHER, differently-shaped version of this defect is a live, separate
question (see the fix-round-1 report): its own credit memo, CM-041, prints the transaction's own
desc verbatim when no items are declared for it — a genuine finding, but not one this test's
mechanism can respect without false-flagging every clinic item table, and not one this task can
fix: the generator that decides this is ../practicesets/generators/gendocs.py, read-only to this
worktree.

── Which of these can still fail, now that Riverbend reads off its envelope too ──

Riverbend's text is scraped from the printed artefact's html by the same `_Reading`, so what was
said of the clinic above is now said of both packs: nothing in this repository writes txn["desc"]
into a document Riverbend ships, and the `_text_alternative` that used to is on a code path
neither pack takes. It would be easy to call
test_no_riverbend_document_carries_a_description_row unfalsifiable on that basis, and it is worth
recording that it is **not**. The row comes back from one line in build_pack.py's manifest arm —
appending ["Description", the transaction's own desc] to the reading — and both assertions in
this file fail when it does; that was run, not reasoned about (see the task-5 report). So this is
neither of the two unfalsifiable kinds. The defect's *original* mechanism is designed out; the
defect itself is one line away, which is exactly the distance a regression travels, and that is
why the assertion stays rather than being retired as proven impossible.

test_no_riverbend_document_states_its_own_designed_error is the live one, and the move cost it two
of its five phrases. "in full" (D04) and "FOB shipping point" (D07) are now printed on the paper
itself: the customer's remittance advice says it is paying in full, and the vendor's invoice
states its own freight terms. Neither is an answer. The freight terms are the *evidence* the
freight entry is made from — asserting them absent would be asserting that the document be
unreadable. So both were re-pointed at the part of the model's description that is genuinely the
author talking and is nowhere on the artefact: the invoice date that puts D04 outside its
discount period, and the ordered quantity D07's own summary counted out in words. Both are in
txn["desc"] in all three versions and in no artefact's text in any of them.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PACKS = ("riverbend", "alderfinch")

# Each designed error, and the phrase the Description row used to hand the student. Written out
# rather than derived: deriving them from the same source that produced them could not fail.
#
# Each phrase must hold for all three versions. D22's figures rotate per version — 40 billed
# against 38 received in A, 44/42 in B, 48/46 in C — so the phrase is the part that gives the
# trap away whatever the quantities are. "receiving report shows 38 received" would have been
# an assertion that could not fail for two versions out of three.
#
# Keyed on the artefact that is the *evidence* for the transaction, which is where a reinstated
# Description row would land: the vendor invoice, not the purchase order that shares its
# transaction. D07 and D22 are purchase orders in the envelope and were re-pointed at D07-2 and
# D22-2 for that reason.
#
# D04's phrase was "in full" and D07's was "FOB shipping point"; see the module docstring for why
# neither can be asserted absent now that the paper prints both. "Nov 24" is the invoice date
# that makes D04's discount unearned, and it is the author's, not the remittance's — the advice
# says only "Payment in full of the balance shown". "60 cassettes" is the summary counting out an
# order the invoice itemises as "11-speed cassette", so it cannot be reached from the artefact
# either, and unlike D22's quantities it does not rotate by version.
GAVE_THE_ANSWER_AWAY = {
    "D04": "Nov 24",
    "D07-2": "60 cassettes",
    "D18": "within 1/15 discount",
    "D22-2": "receiving report shows",
    "D23": "outside the discount period",
}


def _documents(slug: str):
    return json.loads((ROOT / "packs" / slug / "source.json").read_text())["documents"]


def test_no_riverbend_document_carries_a_description_row():
    """Riverbend-only: see the module docstring for why the clinic is not parametrised in here."""
    slug = "riverbend"
    offenders = []
    for document in _documents(slug):
        for code, variant in document["variants"].items():
            fields = (variant.get("text_alternative") or {}).get("fields") or []
            if any(label == "Description" for label, _ in fields):
                offenders.append(f"{document['ref']}/{code}")

    assert not offenders, (
        f"{slug}: {len(offenders)} still describe the transaction: {offenders[:6]}"
    )


def test_no_riverbend_document_states_its_own_designed_error():
    """The five traps, by the phrase each used to give away. A student has to find these by
    reading the documents, which is the skill the set exists to teach."""
    by_ref = {d["ref"]: d for d in _documents("riverbend")}

    for ref, phrase in GAVE_THE_ANSWER_AWAY.items():
        document = by_ref[ref]
        for code, variant in document["variants"].items():
            text = json.dumps(variant.get("text_alternative") or {})
            assert phrase not in text, f"{ref}/{code} still says {phrase!r}"


# A dollar figure, however it is written: "3,840.00", "(89.60)", or the clinic's own unlabelled
# "AMOUNT 2,200.00" / "$ 2,200.00". Two decimal places is what separates this from a reference
# number or a quantity ("12", "RV-2210"), which is why a bare \d+ would not do.
_MONEY = re.compile(r"\d[\d,]*\.\d{2}")


def _has_derivable_amount(text_alt: dict) -> bool:
    """Whether a student reading this one variant can find the figure to journalise, in whatever
    form this pack prints it.

    Three routes, because the two packs print a figure differently and neither is "the" form:
    a clean ``Amount`` label (originally the clinic's three cleanly-labelled documents) is
    checked first and always counts, even where its value is itself "None stated" — that is an
    explicit, authored statement that there is no figure, not an absence of one. Non-empty
    ``lines`` with a money-shaped cell covers a document whose figure is only in its item table
    (its own total is what a student adds up). A blank label whose value is money-shaped was
    written for the clinic's unlabelled html text ("Pay to the order of ... $ 2,200.00") — a
    figure hiding with no label to find it by.

    That was the picture before Riverbend read off its own printed envelope instead of a
    synthesised summary. It no longer holds: measured on the committed v6 pack, Riverbend carries
    **zero** ``Amount``-labelled fields (route 1 is dead here) and **1,488** blank-labelled
    fields, of which 141 are money-shaped. Of the 84 entered document/version pairs, 36 find
    their figure in the item table (route 2) and the other **48 reach it only through a blank
    label** (route 3) — the opposite of what this docstring used to claim, and the reverse of
    which route is load-bearing. The scraped artefact text simply doesn't carry a labelled
    ``Amount`` row the way the old synthesised summaries did; the figures come off the
    artefact's own printed lines (an item table's total, or a bare money-shaped line of text)
    rather than a field authored to say "Amount".

    The test still bites, which is the part worth keeping true: emptying ``lines`` fails 33
    cases (the item-table route), and dropping ``fields`` fails 48 (the blank-label route) —
    checked by mutation, not assumed. A *labelled* breakdown field such as "Invoice amount" or
    "Less 2% cash discount" still does NOT count on its own, on purpose, so that a document
    carrying only those and no money-shaped blank field or item line still fails here exactly as
    it should.
    """
    fields = text_alt.get("fields") or []
    lines = text_alt.get("lines") or []
    if any(label == "Amount" for label, _value in fields):
        return True
    if any(_MONEY.search(str(cell)) for row in lines for cell in row):
        return True
    if any(label == "" and _MONEY.search(value) for label, value in fields):
        return True
    return False


@pytest.mark.parametrize("slug", PACKS)
def test_every_entered_document_carries_its_own_amount(slug):
    """Every document a student actually has to journalise must carry a figure they can find.

    Replaces test_every_document_still_identifies_itself, which asserted only that a document
    said *something* beyond its own date and name — satisfied by any two unrelated fields, so it
    could not fail on the one thing that actually mattered: a reviewer deleted every Amount row
    from every Riverbend document and all of that test's assertions still passed, D16 (genuinely
    unreadable at the time) among them. This checks for the figure specifically.

    Scoped to documents the answer key's own `triage` says take an entry: a no-entry document
    (an enquiry, a price list, a void cheque, an appointment request) is correctly allowed to
    carry no derivable amount at all, and four Riverbend documents that DO take an entry — three
    cash register tapes and the payroll register's employer-FICA entry — correctly carry no party
    of any kind, which is why this does not also require one.
    """
    data = json.loads((ROOT / "packs" / slug / "source.json").read_text())
    offenders = []
    for document in data["documents"]:
        ref = document["ref"]
        for code, variant in document["variants"].items():
            if not data["answers"][code]["triage"].get(ref, True):
                continue
            text_alt = variant.get("text_alternative") or {}
            if not _has_derivable_amount(text_alt):
                offenders.append(f"{document['ref']}/{code}")

    assert not offenders, (
        f"{slug}: {len(offenders)} entered documents carry no derivable amount: {offenders[:6]}"
    )
