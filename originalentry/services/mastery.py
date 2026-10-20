"""What a class does not understand, per assignment.

Two measures, deliberately not comparable and deliberately never ranked against each other:

*Process* concepts are scored, so their mastery is a share of marks, pooled across the cohort.
*Topic* concepts are recognised from error signatures, which carry no marks -- and
``grading.signatures.detect`` returns nothing at all for empty books, so **absence of a signature
is not evidence of understanding**. A "share of students clear" would therefore improve as
students did less work. Topic concepts are counted in students instead, never expressed as a
percentage, which is why this module has no single ``mastery`` number.

Marks come from ``grades.final_marks``, never the raw engine result: overrides are what the
student's marks page, the grading pages, the marks export and this screen's own CSV all show, and
a figure that disagreed with the CSV beside it would be worse than no figure.

Nothing under ``grading/`` may import this module. A concept tag must never become an input to a
grade; ``tests/guards/test_import_boundaries.py`` enforces it.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..extensions import db
from ..models import KIND_COMPONENT, Concept, ConceptTag, Workspace
from .grades import SUBMITTED, SUBMITTED_LATE, final_marks, submission_status

#: Below this share of an assignment's marks, a student is counted as needing support. A starting
#: guess, to be revised once a term of real data exists -- not a config flag, because it is not a
#: kill switch and should not borrow the reasoning of one.
SUPPORT_THRESHOLD = 70.0

#: The row that holds components no concept claims. It is shown rather than dropped, so the view
#: never silently describes less of the assignment than it appears to, and it sorts last whatever
#: its percentage because it is not something anyone can reteach.
UNTAGGED = "untagged"
UNTAGGED_LABEL = "Untagged"


@dataclass(frozen=True)
class ConceptMastery:
    key: str
    label: str
    points: float
    max_points: float

    @property
    def percent(self) -> float:
        return 100 * self.points / self.max_points if self.max_points else 0.0


@dataclass(frozen=True)
class MasteryReport:
    submitted: int
    total: int
    needs_support: int
    concepts: tuple[ConceptMastery, ...] = ()
    weakest: ConceptMastery | None = None


def rank_concepts(marks: list, tags: dict[str, tuple[str, str]]) -> tuple[ConceptMastery, ...]:
    """Pool each concept's marks across every student, weakest first.

    Pooled, not averaged: one student scoring 1/10 and another 18/20 is 19/30, not the mean of
    their two percentages. The two agree whenever every student has the same ``max_points``, which
    is exactly why averaging survives casual testing.

    ``tags`` maps a component key to ``(concept_key, concept_label)``. A component with no entry
    pools into ``UNTAGGED``.
    """
    totals: dict[str, list[float]] = {}
    labels: dict[str, str] = {}
    for student in marks:
        for component in student.components:
            key, label = tags.get(component.key, (UNTAGGED, UNTAGGED_LABEL))
            labels[key] = label
            running = totals.setdefault(key, [0.0, 0.0])
            running[0] += component.points
            running[1] += component.max_points

    ranked = [
        ConceptMastery(key=key, label=labels[key], points=points, max_points=max_points)
        for key, (points, max_points) in totals.items()
    ]
    # Untagged last whatever its percentage; everything else weakest first, then by key so the
    # order of two equal concepts does not depend on dictionary insertion.
    ranked.sort(key=lambda c: (c.key == UNTAGGED, c.percent, c.key))
    return tuple(ranked)


def _component_tags(session) -> dict[str, tuple[str, str]]:
    rows = session.execute(
        db.select(ConceptTag.artifact_key, Concept.key, Concept.label)
        .join(Concept, ConceptTag.concept_id == Concept.id)
        .where(ConceptTag.artifact_kind == KIND_COMPONENT, Concept.retired_at.is_(None))
    ).all()
    return {artifact_key: (key, label) for artifact_key, key, label in rows}


def _workspaces(session, assignment) -> tuple[list, list]:
    """Every live workspace, and the subset a mastery figure is computed over.

    A component's ``max_points`` is always the pack's full weight for that component, so an
    unstarted workspace contributes ``0 / full`` to every concept it touches. Including
    in-progress work would drag every percentage toward zero in proportion to how early in the
    term somebody looked, which is the opposite of degrading gracefully.

    ``submission_status`` rather than ``status == "submitted"`` or ``submitted_at is not None``:
    the three disagree for a workspace that was submitted and then reopened.
    """
    everyone = list(session.scalars(
        db.select(Workspace).where(
            Workspace.assignment_id == assignment.id, Workspace.archived_at.is_(None))
    ).all())
    submitted = [w for w in everyone
                 if submission_status(session, w) in (SUBMITTED, SUBMITTED_LATE)]
    return everyone, submitted


def assignment_mastery(session, assignment) -> MasteryReport:
    """Block A of the Diagnostics screen: ranked mastery, and who needs support."""
    everyone, population = _workspaces(session, assignment)

    marks = [m for m in (final_marks(session, w) for w in population) if m is not None]
    concepts = rank_concepts(marks, _component_tags(session))
    return MasteryReport(
        submitted=len(population),
        total=len(everyone),
        needs_support=sum(1 for m in marks if m.percent < SUPPORT_THRESHOLD),
        concepts=concepts,
        weakest=concepts[0] if concepts else None,
    )
