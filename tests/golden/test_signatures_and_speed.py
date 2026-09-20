"""A10 and A11: every designed error is named, and a section grades fast enough.

**A10** — a pack's key declares the errors its company was built to provoke. Each one has to be
recognised and reported by its label, or the diagnostics screen quietly under-counts a
misconception the instructor needed to hear about. The test walks the key's own signatures, so a
pack that adds one gets covered without anybody remembering to write a case for it.

**A11** — grading a section of forty must finish inside half a minute. This times the engine
itself, which is the part that could grow slow as components are added; the loader and the batched
screen around it are measured on staging.
"""

import copy
import time

import pytest
from originalentry.grading import grade
from originalentry.grading.signatures import BALANCE_DELTA, ENTRY_AMOUNT, ENTRY_LINE
from originalentry.packs import replay, schema

from tests.packs import testco_alpha
from tests.work import perfect_work

SECTION_SIZE = 40
SECTION_BUDGET_SECONDS = 30.0


@pytest.fixture(scope="module")
def pack():
    return schema.load_pack(testco_alpha.PACK)


@pytest.fixture(scope="module")
def key():
    return schema.load_answer_key(testco_alpha.KEY_A)


def _key_with(mutate) -> dict:
    """A key a student might have worked from, having made one designed error."""
    worked = copy.deepcopy(testco_alpha.KEY_A)
    mutate(worked)
    return worked


def _work_making(signature, pack, key):
    """Build work that commits the error this signature describes, however it is detected."""
    detect = signature.detect or {}
    kind = detect.get("type")

    if kind in (ENTRY_LINE, ENTRY_AMOUNT):
        document = detect["document"]

        def mutate(worked):
            entry = next(e for e in worked["expected_entries"] if e["document"] == document)
            side = detect["side"]
            amount = detect.get("amount")
            for line in entry["lines"]:
                # Move the line on the same side onto the account the signature names.
                if (side == "debit" and line.get("debit")) or (
                    side == "credit" and line.get("credit")
                ):
                    line["account"] = detect["account"]
                    if amount is not None:
                        line[side] = amount
                        other = "credit" if side == "debit" else "debit"
                        for counterpart in entry["lines"]:
                            if counterpart is not line and counterpart.get(other):
                                counterpart[other] = amount
                    break

        return perfect_work(pack, key, snapshot=replay.build_replay_snapshot(
            pack, schema.load_answer_key(_key_with(mutate))
        ))

    if kind == BALANCE_DELTA:
        # No single document carries this one: drop the adjustment it describes.
        def mutate(worked):
            worked["adjustments"] = []

        snapshot = replay.build_replay_snapshot(
            pack, schema.load_answer_key(_key_with(mutate))
        )
        return perfect_work(pack, key, snapshot=snapshot)

    raise AssertionError(f"unknown detect type {kind!r}")


def test_a10_every_designed_error_in_the_pack_can_be_named(pack, key):
    assert key.error_signatures, "this pack declares no designed errors to recognise"

    for signature in key.error_signatures:
        result = grade(_work_making(signature, pack, key), pack, key)
        named = {found.key: found.label for found in result.signatures}

        assert signature.key in named, (
            f"{signature.key} was not recognised; the screen would under-count it. "
            f"Found instead: {sorted(named)}"
        )
        assert named[signature.key] == signature.label


def test_a10_work_that_follows_the_key_raises_none_of_them(pack, key):
    """The other half of the claim: a signature that fires on good work is worse than none."""
    result = grade(perfect_work(pack, key), pack, key)

    assert result.signatures == ()


def test_a11_a_section_of_forty_grades_well_inside_the_limit(pack, key):
    work = perfect_work(pack, key)

    started = time.perf_counter()
    for _ in range(SECTION_SIZE):
        grade(work, pack, key)
    took = time.perf_counter() - started

    per_workspace = took / SECTION_SIZE
    assert took < SECTION_BUDGET_SECONDS, (
        f"grading {SECTION_SIZE} took {took:.1f}s ({per_workspace * 1000:.0f}ms each); "
        f"the limit is {SECTION_BUDGET_SECONDS:.0f}s"
    )
