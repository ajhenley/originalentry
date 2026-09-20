"""The grading engine (T8.1).

``grade`` is a pure function: the student's work, the pack and the variant's key in, points and
evidence out. It issues no query and touches no Flask object, so a component can be tested in
milliseconds and a marking rule can be argued about without a database.

The rule it implements is the method-not-match rule: a step earns its marks if it was handled
properly on the student's **own** prior figure. Only ``entry_accuracy`` and (later)
``adjustment_amounts`` compare a figure with the key, and both do it one item at a time.
"""

from __future__ import annotations

from .components import COMPONENTS
from .models import Deduction, GradeResult, StudentWork
from .signatures import detect

ENGINE_VERSION = "0.1.0"


def grade(work: StudentWork, pack, key) -> GradeResult:
    results = []
    for component in pack.rubric.components:
        run = COMPONENTS.get(component.key)
        if run is None:  # a pack may name a component this engine version does not run yet
            continue
        results.append(run(work, pack, key, float(component.points)))

    signatures, unexplained = detect(work, pack, key)
    deductions, review_reasons = _deductions(signatures, key)
    return GradeResult(
        engine_version=ENGINE_VERSION,
        components=tuple(results),
        signatures=signatures,
        unexplained=unexplained,
        deductions=deductions,
        review_reasons=review_reasons,
    )


def _deductions(signatures, key) -> tuple[tuple[Deduction, ...], tuple[str, ...]]:
    """What the pack asked to be taken off for the errors the engine recognised (T8.5).

    A signature is diagnosis and changes no mark unless the pack sets ``deduct_points``. Two
    rules govern what happens when it does:

    * It applies **once** per signature. Marking one slip twice is not a stricter rule, it is a
      different mark.
    * Only a signature the engine is **sure of** deducts. The balance-delta fallback reports a
      possibility, and this app does not take marks off a maybe — it says so and sends the
      workspace to a grader, who decides with the evidence in front of them.
    """
    asked = {s.key: s.deduct_points for s in key.error_signatures if s.deduct_points}
    deductions, reasons, seen = [], [], set()
    for found in signatures:
        points = asked.get(found.key)
        if not points or found.key in seen:
            continue
        seen.add(found.key)
        if found.confident:
            deductions.append(Deduction(found.key, found.label, float(points)))
        else:
            reasons.append(
                f"The pack deducts {points} for “{found.label}”, but this was read from the "
                "balances and is only a possibility. Decide it by hand."
            )
    return tuple(deductions), tuple(reasons)
