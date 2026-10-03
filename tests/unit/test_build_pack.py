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


# ── Refusals from the manifest path ──────────────────────────────────────────
#
# Each of these three lookups died with a bare `KeyError: 2` raised out of a dict comprehension,
# which is loud but unhelpful: it names neither the artefact nor the transaction nor what was
# written, and every other refusal in this file ends "Nothing was written." They fire where the
# envelope and the model disagree about which artefact is the evidence for which transaction,
# which is precisely the disagreement the whole manifest path exists to resolve.

def _clinic():
    """The clinic's model, errors and profile, plus a minimal manifest of its own shape."""
    _require_sets()
    script = _script()
    model, errors_mod = script.load_model(script.require_practicesets(PRACTICESETS), "alderfinch")
    profile = script.load_profile("alderfinch")
    return script, model, errors_mod, profile


def _inventory(model, drop=None):
    """One manifest entry per transaction, as the envelope's own manifest.json is shaped."""
    return [{"ref": f"D{t['no']:02d}", "kind": "sales_invoice", "printed_ref": str(t["no"]),
             "date": t["date"], "entry_for": None if t["no"] == drop else t["no"]}
            for t in model.build("B")]


def test_a_transaction_no_artefact_is_evidence_for_is_named():
    """The envelope prints nothing that is the evidence for transaction 2 — so the key would have
    an entry with no document to attach it to."""
    script, model, _errors, profile = _clinic()
    orphaned = model.build("B")[1]["no"]

    with pytest.raises(SystemExit) as caught:
        script.expected_entries(model, "B", profile, _inventory(model, drop=orphaned))

    message = str(caught.value)
    assert f"no artefact as the evidence for transaction {orphaned}" in message, message
    assert "Nothing was written" in message, message


def test_the_same_transaction_is_named_when_a_trap_cannot_be_detected():
    """error_signatures resolves the same document the same way: a trap has to be detected on the
    artefact a student journalises from, and there has to be one.

    The transaction has to be one a trap actually moves, or the lookup is never reached — which
    is why this reads it out of TRAPS rather than naming a number.
    """
    script, model, errors_mod, _profile = _clinic()
    base = {t["no"]: t["lines"] for t in model.build("B")}
    orphaned = next(no for kind, _date, _label in errors_mod.TRAPS
                    for no, txn in ((t["no"], t) for t in errors_mod.mutate("B", kind))
                    if txn["lines"] != base[no])

    with pytest.raises(SystemExit) as caught:
        script.error_signatures(model, errors_mod, "B", _inventory(model, drop=orphaned))

    message = str(caught.value)
    assert f"no artefact as the evidence for transaction {orphaned}" in message, message
    assert "Nothing was written" in message, message


def test_an_entry_for_the_model_has_no_transaction_for_is_named():
    """The other direction: the envelope names a transaction number this version does not have,
    which is what a renumbered transaction looks like from here."""
    script, model, _errors, profile = _clinic()
    manifest = _inventory(model)
    manifest[0] = {**manifest[0], "entry_for": 997}
    txns_by_no = {t["no"]: t for t in model.build("B")}

    with pytest.raises(SystemExit) as caught:
        script._designated_journals(manifest, txns_by_no, profile, "B")

    message = str(caught.value)
    assert profile.COMPANY["slug"] in message, message
    assert f"{manifest[0]['ref']} is the evidence for transaction 997" in message, message
    assert "no transaction numbered" in message, message
    assert "Nothing was written" in message, message


# ── The pack's own version number ────────────────────────────────────────────────────────

def test_the_pack_version_defaults_to_one():
    """Unchanged behaviour for every existing caller: a build with no version is version 1."""
    source = _script().build_source("riverbend", PRACTICESETS)

    assert source["version"] == 1


def test_the_pack_version_can_be_raised_for_a_correction():
    """A pack version is immutable once a workspace pins it, so a correction to a pack already in
    the catalogue has to arrive as a NEWER version -- rule V14 refuses it otherwise. The number was
    hardcoded, so no correction to either live pack could be imported at all.
    """
    source = _script().build_source("riverbend", PRACTICESETS, version=2)

    assert source["version"] == 2


def test_a_pack_version_below_one_is_refused():
    """Versions count up from one. A zero or a negative would validate as a pack and then be
    unimportable for a reason nobody could read off the archive."""
    with pytest.raises(SystemExit) as refusal:
        _script().build_source("riverbend", PRACTICESETS, version=0)

    assert "Nothing was written." in str(refusal.value)
