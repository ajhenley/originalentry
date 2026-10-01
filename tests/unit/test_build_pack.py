"""The translator's own behaviour, as distinct from any pack it produces.

The script this replaces pointed at a directory that had been refactored away. Its documented
command raised FileNotFoundError and nothing noticed, so the pack it maintains drifted until a
figure had to be corrected by hand. A quiet failure here is the defect, not the symptom.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PRACTICESETS = ROOT.parent / "practicesets"


def _script():
    """scripts/ is not a package, so the module is loaded by path."""
    spec = importlib.util.spec_from_file_location(
        "build_pack", ROOT / "scripts" / "build_pack.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_it_names_what_is_missing_rather_than_failing_obscurely(tmp_path):
    missing = tmp_path / "nowhere"

    with pytest.raises(SystemExit) as caught:
        _script().require_practicesets(missing)

    message = str(caught.value)
    assert str(missing / "generators" / "model.py") in message, message
    assert "Nothing was written" in message, message


@pytest.mark.skipif(not PRACTICESETS.is_dir(), reason="practicesets is not checked out beside us")
def test_it_accepts_the_real_checkout():
    assert _script().require_practicesets(PRACTICESETS).name == "generators"


@pytest.mark.skipif(not PRACTICESETS.is_dir(), reason="practicesets is not checked out beside us")
def test_two_companies_in_one_process_do_not_return_the_same_figures():
    """model.py reads PRACTICESET_COMPANY when it is imported. Without clearing the module
    cache the second company silently returns the first one's model, and every figure in the
    second pack would be wrong while every test still passed."""
    script = _script()
    generators = script.require_practicesets(PRACTICESETS)

    riverbend, _ = script.load_model(generators, "riverbend")
    alderfinch, _ = script.load_model(generators, "alderfinch")

    assert riverbend.SLUG == "Riverbend"
    assert alderfinch.SLUG == "Alder-and-Finch"
    assert len(riverbend.JOURNALS) == 4
    assert len(alderfinch.JOURNALS) == 3
