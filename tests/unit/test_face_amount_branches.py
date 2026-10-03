"""Which branch of ``_face_amount`` resolves each of Riverbend's entered documents (F4).

A controller ruling once said three documents reach the `sum of debits` fallback -- D16, D26 and
D27 -- and that the sum is genuinely right for the two cheques, so the fallback should not be
re-engineered. Instrumenting the chain itself shows D26 and D27 never reach it at all: they are
cheques, they credit cash, and the first branch returns before the fallback is ever considered.
After the "returns" branch was added for the credit memo, exactly one document reaches the
fallback: D25, the payroll register's employer-FICA entry, where the sum of debits is a single
debit and is the right figure for an unrelated reason (nothing to double-count).

The ruling's conclusion -- leave the fallback alone -- still stands; this pins the fact that
justifies it, so a future change that silently routes some other document onto the fallback, which
is where a fabricated figure comes from (D16's old 1,035.00), fails here.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PRACTICESETS = ROOT.parent / "practicesets"
ALLOW_NO_SETS = os.environ.get("PACK_TRANSLATOR_ALLOW_NO_SETS") == "1"


def _require_sets():
    """Absence of the practice sets fails rather than skips, as the other tests that exercise the
    translator against real figures do: left as a skip this vanishes in any environment without
    the sibling checkout, which is every CI run this repository has."""
    if PRACTICESETS.is_dir():
        return
    if ALLOW_NO_SETS:
        pytest.skip("PACK_TRANSLATOR_ALLOW_NO_SETS=1")
    pytest.fail(
        f"The practice sets are not at {PRACTICESETS}, so _face_amount cannot be exercised "
        f"against Riverbend's real transactions. Check practicesets out beside this repository, "
        f"or set PACK_TRANSLATOR_ALLOW_NO_SETS=1 to accept the gap knowingly."
    )


def _build_pack_module():
    """scripts/ is not a package, so build_pack.py is loaded by path, as every other test that
    needs it does."""
    spec = importlib.util.spec_from_file_location(
        "build_pack", ROOT / "scripts" / "build_pack.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_only_d16_reaches_returns_and_only_d25_reaches_the_fallback():
    _require_sets()
    bp = _build_pack_module()
    model, _errors = bp.load_model(bp.require_practicesets(PRACTICESETS), "riverbend")
    profile = bp.load_profile("riverbend")

    by_branch: dict[str, set[str]] = {}
    for code in sorted(model.VARIANTS):
        for txn in model.build(code):
            # The branch the function itself would take, not a second reading of its lines.
            branch, _amount = bp._face_amount_branch(txn, profile)
            by_branch.setdefault(branch, set()).add(bp._ref(txn))

    assert by_branch.get("returns", set()) == {"D16"}, by_branch.get("returns")
    assert by_branch.get("fallback", set()) == {"D25"}, by_branch.get("fallback")
