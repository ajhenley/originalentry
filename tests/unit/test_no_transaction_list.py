"""The product's claim, kept: there is no transaction list.

README.md and CASES.md both say it in bold. The online pack said otherwise, one line per
document: every Riverbend document carried a "Description" row holding the model's own
description of the transaction, and for five of them that row stated the designed error the
student was supposed to find for themselves.

One assertion over both packs, because the row had two sources — the builder wrote 84 of the 93
document/variant pairs from txn["desc"] and the profile authored the other 9 — and a change that
fixed one source looked complete.
"""

from __future__ import annotations

import json
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
GAVE_THE_ANSWER_AWAY = {
    "D04": "in full",
    "D07": "FOB shipping point",
    "D18": "within 1/15 discount",
    "D22": "receiving report shows",
    "D23": "outside the discount period",
}


def _documents(slug: str):
    return json.loads((ROOT / "packs" / slug / "source.json").read_text())["documents"]


@pytest.mark.parametrize("slug", PACKS)
def test_no_document_carries_a_description_row(slug):
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


@pytest.mark.parametrize("slug", PACKS)
def test_every_document_still_identifies_itself(slug):
    """Removing a row must not leave a document a student cannot read. Riverbend has no images,
    so this text is the whole document."""
    for document in _documents(slug):
        for code, variant in document["variants"].items():
            text_alt = variant.get("text_alternative") or {}
            fields = text_alt.get("fields") or []
            informative = {label for label, _ in fields} - {"Date", "Document"}
            assert informative or text_alt.get("lines"), (
                f"{slug} {document['ref']}/{code} says nothing but its own name and date"
            )
