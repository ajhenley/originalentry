"""The translator's own behaviour, as distinct from any pack it produces.

The script this replaces pointed at a directory that had been refactored away. Its documented
command raised FileNotFoundError and nothing noticed, so the pack it maintains drifted until a
figure had to be corrected by hand. A quiet failure here is the defect, not the symptom.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PRACTICESETS = ROOT.parent / "practicesets"
ALLOW_NO_SETS = os.environ.get("PACK_TRANSLATOR_ALLOW_NO_SETS") == "1"


def _script():
    """scripts/ is not a package, so the module is loaded by path."""
    spec = importlib.util.spec_from_file_location(
        "build_pack", ROOT / "scripts" / "build_pack.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def test_it_names_what_is_missing_rather_than_failing_obscurely(tmp_path):
    missing = tmp_path / "nowhere"

    with pytest.raises(SystemExit) as caught:
        _script().require_practicesets(missing)

    message = str(caught.value)
    assert str(missing / "generators" / "model.py") in message, message
    assert "Nothing was written" in message, message


def test_it_accepts_the_real_checkout():
    _require_sets()
    assert _script().require_practicesets(PRACTICESETS).name == "generators"


def test_two_companies_in_one_process_do_not_return_the_same_figures():
    """model.py reads PRACTICESET_COMPANY when it is imported. Without clearing the module
    cache the second company silently returns the first one's model, and every figure in the
    second pack would be wrong while every test still passed."""
    _require_sets()
    script = _script()
    generators = script.require_practicesets(PRACTICESETS)

    riverbend, _ = script.load_model(generators, "riverbend")
    alderfinch, _ = script.load_model(generators, "alderfinch")

    assert riverbend.SLUG == "Riverbend"
    assert alderfinch.SLUG == "Alder-and-Finch"
    assert len(riverbend.JOURNALS) == 4
    assert len(alderfinch.JOURNALS) == 3
