"""``scripts/build_walkthrough.py``'s own logic, independent of either pack (F2, F7).

``instructor_sections`` decides "this document needs no entry" from two places that used to be
able to disagree: the absence of an expected entry, and V17's own ``key.triage``. They agreed in
both shipped packs, but a document whose triage said it took an entry while the key held none was
reachable and unrefused. This drives the function directly, with the smallest src/key dicts that
satisfy it, so each of its three states — filed, entered, broken — is proved on its own rather than
through whichever state the shipped packs happen to be in.

F7 is folded in here because fixing it meant being back in this file anyway: the walkthrough's
output path was hardcoded under packs/riverbend/, so building any other pack's instructor copy
silently overwrote Riverbend's committed PDF.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _module():
    """scripts/ is not a package, so the module is loaded by path, as the pack-level tests do."""
    path = ROOT / "scripts" / "build_walkthrough.py"
    spec = importlib.util.spec_from_file_location("build_walkthrough_states", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = _module()


def _src(ref: str = "D01") -> dict:
    return {
        "accounts": [{"number": "101", "name": "Cash"}],
        "parties": [],
        "journals": [{"key": "general", "name": "General Journal"}],
        "documents": [{"ref": ref, "display_ref": ref, "date": "2026-12-01",
                       "received_seq": 1}],
        "checkpoints": [],
    }


def test_a_filed_document_prints_its_reason():
    """triage says D01 takes no entry, and the key gives the reason (V17's own field)."""
    key = {"triage": {"D01": False}, "triage_reasons": {"D01": "No order is placed."},
           "expected_entries": [], "checkpoints": {}, "error_signatures": []}

    html = MODULE.instructor_sections(_src(), "A", key)

    assert "No order is placed." in html
    assert "no entry required" in html


def test_an_entered_document_prints_its_entry():
    """triage says D01 takes an entry, and the key holds one."""
    key = {"triage": {"D01": True}, "triage_reasons": {},
           "expected_entries": [{"document": "D01", "journal": "general", "kind": "regular",
                                  "lines": [{"account": "101", "debit": 6000},
                                            {"account": "101", "credit": 6000}]}],
           "checkpoints": {}, "error_signatures": []}

    html = MODULE.instructor_sections(_src(), "A", key)

    assert "60.00" in html
    assert "no entry required" not in html


def test_a_document_claiming_an_entry_it_does_not_have_is_refused():
    """The state neither half of the old condition could reach: triage says D01 takes an entry,
    and the key holds none for it. A broken pack, refused rather than rendered around."""
    key = {"triage": {"D01": True}, "triage_reasons": {}, "expected_entries": [],
           "checkpoints": {}, "error_signatures": []}

    with pytest.raises(SystemExit) as caught:
        MODULE.instructor_sections(_src(), "A", key)

    message = str(caught.value)
    assert "D01" in message
    assert "Nothing was written." in message


def test_a_filed_document_still_needs_its_reason():
    """The existing refusal survives the rewrite: triage says D01 takes no entry and the key
    gives no reason."""
    key = {"triage": {"D01": False}, "triage_reasons": {}, "expected_entries": [],
           "checkpoints": {}, "error_signatures": []}

    with pytest.raises(SystemExit) as caught:
        MODULE.instructor_sections(_src(), "A", key)

    message = str(caught.value)
    assert "D01" in message
    assert "Nothing was written." in message


# ── F7: the output path ──────────────────────────────────────────────────────────────────


def test_the_output_path_sits_under_the_sources_own_directory():
    source = ROOT / "packs" / "alderfinch" / "source.json"

    out = MODULE._output_path(source, None)

    assert out.parent == source.resolve().parent


def test_two_different_sources_resolve_to_different_paths():
    riverbend = ROOT / "packs" / "riverbend" / "source.json"
    alderfinch = ROOT / "packs" / "alderfinch" / "source.json"

    assert (MODULE._output_path(riverbend, None)
            != MODULE._output_path(alderfinch, None))
    assert (MODULE._output_path(riverbend, "A")
            != MODULE._output_path(alderfinch, "A"))


def test_the_instructor_filename_still_names_its_version():
    source = ROOT / "packs" / "riverbend" / "source.json"

    out = MODULE._output_path(source, "B")

    assert out.name == "walkthrough-instructor-B.pdf"
