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
from .models import GradeResult, StudentWork
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
    return GradeResult(
        engine_version=ENGINE_VERSION,
        components=tuple(results),
        signatures=signatures,
        unexplained=unexplained,
    )
