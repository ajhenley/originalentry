"""Why a document needs no entry belongs with the answer, not on the document.

Riverbend printed the sentence in the text a student reads, which told them the triage answer
to three of its ten triage marks. The clinic, taking its documents from the printed envelope,
had nowhere to put the sentence at all, so its instructor copy printed "no entry required"
above a blank line eleven times.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from originalentry.generator import build
from originalentry.packs import schema
from originalentry.packs.validate import validate_pack

ROOT = Path(__file__).resolve().parents[2]
PACKS = ("riverbend", "alderfinch")


@pytest.fixture(scope="module", params=PACKS)
def pack(request):
    source = json.loads((ROOT / "packs" / request.param / "source.json").read_text())
    return request.param, source, build(source, render_images=False)


def _load_profile(slug: str):
    """The profile module, loaded by path -- the same way scripts/build_pack.py's own
    load_profile does, so this reads the file that was actually authored rather than a cached
    import of it."""
    path = ROOT / "packs" / slug / "profile.py"
    spec = importlib.util.spec_from_file_location(f"{slug}_profile_for_triage_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def test_every_packs_committed_reason_is_the_one_its_profile_authored(pack):
    """Ties the committed pack back to what was authored (M5): nothing before this tied the
    committed `triage_reasons` to the profile's `FILED_REASONS`, so a ref dropped, substituted or
    truncated on the way into source.json would commit silently. Replaces
    test_the_reason_is_authored_once_and_not_per_version, which could not fail: `_triage_reasons`
    reads one `FILED_REASONS` and writes the same string into every version, so divergence across
    versions was unconstructable by any single-line change. This asserts against the author
    instead of against itself, and it is the first thing in this file that covers the clinic.

    A profile may author by ref (the clinic's eleven, each its own sentence) or by kind
    (Riverbend's thirty-four filed artefacts in nine kinds), so the expected sentence is resolved
    the same two ways round -- but from the **committed pack's** own `kind` field rather than from
    the envelope's manifest, which is what `_triage_reasons` reads. The two sources agree only if
    the builder carried the kind into the document it wrote, so this still fails if a sentence is
    substituted, truncated or attached to the wrong kind; it does not become a restatement of the
    function it is checking.

    A filed ref whose kind resolves to nothing is named rather than skipped: that is precisely the
    hole -- an envelope kind nobody authored a sentence for -- that V17 would otherwise be left to
    find on its own.
    """
    slug, source, generated = pack
    profile = _load_profile(slug)
    kind_of = {document["ref"]: document.get("kind") for document in source["documents"]}

    for code, key in generated.keys.items():
        filed = {ref for ref, needs_entry in key["triage"].items() if not needs_entry}
        assert set(key["triage_reasons"]) == filed, (
            f"{slug} {code}: refs carrying a reason do not match the refs filed"
        )
        for ref in filed:
            authored = profile.FILED_REASONS.get(ref) or profile.FILED_REASONS.get(kind_of[ref])
            assert authored, (
                f"{slug} {code}: {ref} is a {kind_of[ref]!r} and FILED_REASONS authors a sentence "
                f"for neither that ref nor that kind"
            )
            assert key["triage_reasons"][ref] == authored, (
                f"{slug} {code}: {ref}'s committed reason does not match the one FILED_REASONS "
                f"authors for it"
            )


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


# ── V17 ──────────────────────────────────────────────────────────────────────────────────


def _pack_and_keys(slug: str):
    source = json.loads((ROOT / "packs" / slug / "source.json").read_text())
    generated = build(source, render_images=False)
    return schema.load_pack(generated.pack), {
        code: schema.load_answer_key(key) for code, key in generated.keys.items()
    }


@pytest.mark.parametrize("slug", PACKS)
def test_both_packs_satisfy_v17(slug):
    pack, keys = _pack_and_keys(slug)

    assert [p for p in validate_pack(pack, keys) if p.rule == "V17"] == []


def test_v17_reports_a_filed_document_with_no_reason():
    pack, keys = _pack_and_keys("alderfinch")
    keys["A"].triage_reasons.pop("N06")

    problems = [p for p in validate_pack(pack, keys) if p.rule == "V17"]

    assert len(problems) == 1, problems
    assert "N06" in problems[0].message
    assert problems[0].path == "answer_keys.A.triage_reasons"


def test_v17_reports_a_reason_left_on_a_document_that_takes_an_entry():
    """The half that stops the map rotting: a set changes, a document starts taking an entry,
    and the sentence saying it needs none is still there."""
    pack, keys = _pack_and_keys("alderfinch")
    entered = next(ref for ref, needs in keys["A"].triage.items() if needs)
    keys["A"].triage_reasons[entered] = "Left behind by an earlier version of this set."

    problems = [p for p in validate_pack(pack, keys) if p.rule == "V17"]

    assert len(problems) == 1, problems
    assert entered in problems[0].message


def test_v17_reports_a_reason_that_is_only_whitespace():
    pack, keys = _pack_and_keys("alderfinch")
    keys["A"].triage_reasons["N06"] = "   "

    problems = [p for p in validate_pack(pack, keys) if p.rule == "V17"]

    assert len(problems) == 1, problems
    assert "N06" in problems[0].message


# ── Reasons authored by kind ─────────────────────────────────────────────────────────────

def _profile_with(filed_reasons):
    class P:
        FILED_REASONS = filed_reasons
    return P()


def _bp():
    import importlib.util
    spec = importlib.util.spec_from_file_location("build_pack", ROOT / "scripts" / "build_pack.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MANIFEST = [
    {"ref": "N01", "kind": "time_card"},
    {"ref": "N02", "kind": "time_card"},
    {"ref": "N03", "kind": "price_list"},
    {"ref": "D01", "kind": "cheque"},
]
TRIAGE = {"N01": False, "N02": False, "N03": False, "D01": True}


def test_a_reason_keyed_by_kind_reaches_every_document_of_that_kind():
    """Riverbend files 34 documents of nine kinds. Authoring 34 sentences would be nine
    sentences and twenty-five copies of them."""
    reasons = _bp()._triage_reasons(
        _profile_with({"time_card": "Supporting record for the payroll cheque."}),
        TRIAGE, manifest=MANIFEST,
    )

    assert reasons == {"N01": "Supporting record for the payroll cheque.",
                       "N02": "Supporting record for the payroll cheque."}


def test_a_reason_keyed_by_ref_wins_over_its_kind():
    """One document of a kind sometimes needs its own sentence; the specific beats the general."""
    reasons = _bp()._triage_reasons(
        _profile_with({"time_card": "The general one.", "N02": "This one is different."}),
        TRIAGE, manifest=MANIFEST,
    )

    assert reasons["N01"] == "The general one."
    assert reasons["N02"] == "This one is different."


def test_a_kind_reason_never_reaches_a_document_that_takes_an_entry():
    """V17 forbids a reason on a document that needs an entry, so the expansion must respect
    triage rather than paint every document of a kind."""
    reasons = _bp()._triage_reasons(
        _profile_with({"cheque": "Should not appear."}), TRIAGE, manifest=MANIFEST,
    )

    assert reasons == {}


def test_without_a_manifest_only_ref_keys_resolve():
    """Riverbend's own pack built before this change, and the clinic's, pass no manifest here."""
    reasons = _bp()._triage_reasons(
        _profile_with({"time_card": "By kind.", "N03": "By ref."}), TRIAGE,
    )

    assert reasons == {"N03": "By ref."}
