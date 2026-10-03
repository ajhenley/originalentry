"""The bridge between the paper set and the pack, kept standing.

A translator exists so the figures are authored once. It only delivers that if someone notices
when it stops working. The script this replaces pointed at a directory that had been refactored
away, and the pack it maintains went stale with nothing watching, until a money figure had to be
corrected by editing the JSON three times by hand.

This test is the thing that was missing.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PRACTICESETS = ROOT.parent / "practicesets"
LIVE = ROOT / "packs" / "riverbend" / "source.json"
ALLOW_NO_SETS = os.environ.get("PACK_TRANSLATOR_ALLOW_NO_SETS") == "1"

# The versions the envelope is printed in. Riverbend has these three, and the figures on the
# artefacts are the whole difference between them, so one set cannot stand in for the others.
CODES = ("A", "B", "C")


def _require_sets():
    """Absence of the practice sets fails rather than skips.

    These two tests are the only ones that exercise the translator against real figures. Left as
    a skip they vanish in any environment without the sibling checkout — which is every CI run
    this repository has — and the suite reports green having tested nothing. Opting out is
    deliberate and has to be spelled.
    """
    if PRACTICESETS.is_dir():
        return
    if ALLOW_NO_SETS:
        pytest.skip("PACK_TRANSLATOR_ALLOW_NO_SETS=1")
    pytest.fail(
        f"The practice sets are not at {PRACTICESETS}, so the only tests that exercise the "
        f"translator against real figures cannot run. Check practicesets out beside this "
        f"repository, or set PACK_TRANSLATOR_ALLOW_NO_SETS=1 to accept the gap knowingly."
    )


@pytest.fixture(scope="module")
def envelope(tmp_path_factory):
    """The printed envelope, three times over: one directory per version, as gendocs.py writes
    it. Produced the same way tests/unit/test_document_manifest.py's own fixture produces the
    clinic's, and module-scoped so the three versions are printed once for this whole file.

    The committed pack's documents, its triage and the text a student reads all come off these
    artefacts now, so a rebuild without them is not the same pack: it would be the retired
    one-document-per-transaction pack, 28 documents against the committed 62, and this file's
    comparison would report a difference it could do nothing about.
    """
    _require_sets()
    out = tmp_path_factory.mktemp("riverbend-envelope")
    for code in CODES:
        env = dict(os.environ, PRACTICESET_COMPANY="riverbend",
                   PRACTICESET_OUT=str(out / code))
        subprocess.run([sys.executable, "generators/gendocs.py", code],
                       cwd=PRACTICESETS, env=env, check=True, capture_output=True)
    return out


def _build(company, envelope, version=1):
    spec = importlib.util.spec_from_file_location(
        "build_pack", ROOT / "scripts" / "build_pack.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # No images_dir, so none of the 186 photographs are rendered: nothing here compares a
    # picture, and WeasyPrint and poppler are laptop-only tooling.
    return module.build_source(
        company, PRACTICESETS, documents_dir=envelope, version=version
    )


def test_regenerating_riverbend_reproduces_the_pack_in_service(envelope):
    """If this fails, either the translator broke or the committed pack has content that no
    longer traces to the practice set. Both are worth stopping for.

    The pack's own declared version is read back rather than assumed: it is a fact about the
    catalogue -- which version of this company is in service -- and nothing in the practice set
    derives it, so a correction raises it and this test must not drift every time one does.
    Everything else here is content, and content is what the translator is answerable for.
    """
    _require_sets()
    live = json.loads(LIVE.read_text())

    assert _build("riverbend", envelope, version=live["version"]) == live


def test_the_corrected_money_figure_comes_from_the_model(envelope):
    """The sharpest single test that the bridge works: this text was once patched into the JSON
    by hand, three times. The model has formatted it correctly for longer than the patch has
    existed, so a working translator emits it unprompted. It reaches the pack off the printed
    remittance advice now rather than out of the profile's own arithmetic, and it is still the
    model's formatting either way."""
    _require_sets()
    text = json.dumps(_build("riverbend", envelope))

    assert "4,390.40" in text
    assert "4390.4" not in text
