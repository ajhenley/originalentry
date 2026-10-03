"""Why a document needs no entry belongs with the answer, not on the document.

Riverbend printed the sentence in the text a student reads, which told them the triage answer
to three of its ten triage marks. The clinic, taking its documents from the printed envelope,
had nowhere to put the sentence at all, so its instructor copy printed "no entry required"
above a blank line eleven times.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from originalentry.generator import build

ROOT = Path(__file__).resolve().parents[2]
PACKS = ("riverbend", "alderfinch")


@pytest.fixture(scope="module", params=PACKS)
def pack(request):
    source = json.loads((ROOT / "packs" / request.param / "source.json").read_text())
    return request.param, source, build(source, render_images=False)


def test_every_filed_document_has_a_reason_in_every_version(pack):
    slug, source, generated = pack

    for code, key in generated.keys.items():
        filed = [ref for ref, needs_entry in key["triage"].items() if not needs_entry]
        assert filed, f"{slug} version {code} files nothing, so this test proves nothing"
        for ref in filed:
            reason = key["triage_reasons"].get(ref, "")
            assert reason.strip(), f"{slug} {code}: {ref} needs no entry and says no why"


def test_no_reason_is_recorded_for_a_document_that_takes_an_entry(pack):
    """A reason left behind on a document that later takes an entry is how a correct note
    becomes a wrong one."""
    slug, source, generated = pack

    for code, key in generated.keys.items():
        entered = [ref for ref, needs_entry in key["triage"].items() if needs_entry]
        stray = [ref for ref in entered if ref in key["triage_reasons"]]
        assert not stray, f"{slug} {code}: {stray} take an entry and carry a no-entry reason"


def test_the_reason_is_authored_once_and_not_per_version(pack):
    """One sentence per ref in the profile, copied into each version. Three divergent copies
    would be three places to correct."""
    slug, source, generated = pack

    by_ref: dict[str, set[str]] = {}
    for key in generated.keys.values():
        for ref, reason in key["triage_reasons"].items():
            by_ref.setdefault(ref, set()).add(reason)

    differing = {ref: texts for ref, texts in by_ref.items() if len(texts) > 1}
    assert not differing, f"{slug}: {sorted(differing)} read differently in different versions"


def test_the_clinic_explains_the_documents_the_envelope_added():
    """The eleven the clinic gained from the printed envelope. Named individually, because
    "eleven have reasons" would pass if the eleven were the wrong eleven."""
    source = json.loads((ROOT / "packs" / "alderfinch" / "source.json").read_text())
    reasons = build(source, render_images=False).keys["A"]["triage_reasons"]

    assert set(reasons) == {
        "D03", "D11", "N01", "N02", "N03", "N04", "N05", "N06", "N07", "N08", "N09",
    }
    assert "voided before use" in reasons["N01"]
    assert "replenished" in reasons["N06"]
    assert "payroll" in reasons["N02"]
