"""The clinic: Alder & Finch Veterinary Clinic, 1-7 December.

The paper practice set is the source of truth and scripts/build_pack.py only translates it. What
this guards is that the translation stayed faithful: the figures the app derives by replaying the
key through its own ledger engine must equal the figures in the paper solution, to the cent, for
all three versions.

If those ever disagree, a student marked by this app and a student marked from the printed key
would receive different marks for the same work.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from originalentry.generator import build
from originalentry.packs import schema
from originalentry.packs.validate import validate_pack, warn_pack

SOURCE = Path(__file__).resolve().parents[2] / "packs" / "alderfinch" / "source.json"

# Computed from the practicesets model with its own trial_balance, which is what prints the
# solution set's Checkpoint Answers page.
PAPER = {
    "A": {"cp1": Decimal("7700.00"), "cp2": Decimal("33943.75"), "cp3": Decimal("3210.00")},
    "B": {"cp1": Decimal("7710.00"), "cp2": Decimal("34043.75"), "cp3": Decimal("3300.00")},
    "C": {"cp1": Decimal("7720.00"), "cp2": Decimal("34143.75"), "cp3": Decimal("3390.00")},
}


@pytest.fixture(scope="module")
def generated():
    return build(json.loads(SOURCE.read_text()), render_images=False)


def test_the_pack_passes_every_rule(generated):
    pack = schema.load_pack(generated.pack)

    assert validate_pack(pack) == []


def test_the_checkpoints_match_the_paper_solution(generated):
    for code, expected in PAPER.items():
        checkpoints = generated.keys[code]["checkpoints"]
        for key, figure in expected.items():
            assert Decimal(checkpoints[key]) / 100 == figure, f"{code} {key}"


def test_no_checkpoint_can_be_passed_by_copying(generated):
    """Three versions exist to make copying visible. A checkpoint that answers the same in all
    three cannot do that, and the clinic's Accounts Payable control is exactly such a figure."""
    for key in ("cp1", "cp2", "cp3"):
        answers = {generated.keys[code]["checkpoints"][key] for code in ("A", "B", "C")}
        assert len(answers) == 3, f"{key} answers the same in more than one version"


def test_a_credit_balance_checkpoint_is_asked_as_a_positive_figure(generated):
    """Unearned Boarding Revenue is a liability and is stored with a negative sign. A student
    reads the balance off a trial balance's credit column and writes it as a positive number;
    asking them for a negative one is a question about this app, not about accounting."""
    for code in ("A", "B", "C"):
        assert generated.keys[code]["checkpoints"]["cp3"] > 0


def test_the_pack_warns_about_nothing(generated):
    pack = schema.load_pack(generated.pack)

    assert list(warn_pack(pack)) == []


# ── The instructor copy must not go out with a blank where a reason belongs ──────────────

def _walkthrough(src: dict, version: str, key: dict) -> str:
    """Load the generator by path: scripts/ is not a package, as test_riverbend_pack.py does."""
    import importlib.util

    path = Path(__file__).resolve().parents[2] / "scripts" / "build_walkthrough.py"
    spec = importlib.util.spec_from_file_location("build_walkthrough_clinic", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.instructor_sections(src, version, key)


def test_the_instructor_copy_says_why_each_filed_document_needs_no_entry(generated):
    """It printed "no entry required" above a blank line eleven times, because it read the
    reason from a "Description" field that a pack built from the printed envelope does not
    have. The reason now comes from the answer key."""
    src = json.loads(SOURCE.read_text())

    html = _walkthrough(src, "A", generated.keys["A"])

    assert "voided before use" in html
    assert "no replenishment cheque is drawn this period" in html
    assert "not card by card" in html
    assert "no entry required" in html


def test_the_instructor_copy_still_refuses_when_a_reason_is_missing(generated):
    """V17 should stop a pack like this reaching here at all. The refusal stays because the
    walkthrough is run by hand against whatever source.json is on disk, which is exactly when
    a blank would go unnoticed."""
    src = json.loads(SOURCE.read_text())
    key = json.loads(json.dumps(generated.keys["A"]))
    key["triage_reasons"].pop("N06")

    with pytest.raises(SystemExit) as refusal:
        _walkthrough(src, "A", key)

    message = str(refusal.value)
    assert "N06" in message
    assert "Nothing was written." in message
