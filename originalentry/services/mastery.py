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
from ..models import (
    GROUP_PROCESS,
    KIND_COMPONENT,
    KIND_SIGNATURE,
    Concept,
    ConceptTag,
    User,
)
from ..workspaces import class_workspaces
from .diagnostics import SignatureCount, cohort_diagnostics
from .grades import SUBMITTED, SUBMITTED_LATE, final_marks, latest_run, submission_status

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
    mistakes: tuple[ConceptMistakes, ...] = ()
    top_mistake: SignatureCount | None = None


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


def weakest_concept(concepts: tuple[ConceptMastery, ...]) -> ConceptMastery | None:
    """The lowest-scoring real concept, for the callout.

    Never the untagged row. "Review Untagged before the next assignment" is not advice anybody
    can act on -- it is a completeness row, there so nothing silently vanishes from the view, not
    a thing that can be taught. When it is the only row there is nothing to recommend at all.
    """
    for concept in concepts:
        if concept.key != UNTAGGED:
            return concept
    return None


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

    ``submission_status`` is named for the lateness and closed-never-handed-in semantics it adds,
    not because it disagrees with ``status == "submitted"`` -- it branches on exactly that, so the
    two agree and both drop a reopened workspace. Only ``submitted_at is not None`` would keep
    one, and keeping it would be wrong twice over: a reopened book is in flux, scored against the
    pack's full weights while the student starts over, so a teacher who reopened work to let
    somebody fix it would watch the class's mastery fall.
    """
    everyone = class_workspaces(session, assignment)
    submitted = [w for w in everyone
                 if submission_status(session, w) in (SUBMITTED, SUBMITTED_LATE)]
    return everyone, submitted


def assignment_mastery(session, assignment, *, diagnostics=None) -> MasteryReport:
    """Both blocks of the Diagnostics screen: ranked mastery, and the mistakes.

    ``diagnostics`` lets the caller hand in a ``CohortDiagnostics`` it already has. The view does,
    for the sections below this one, and recomputing it here would run a ``latest_run`` per
    workspace, the dispositions query, the activity-events query, the triage tallies and the
    quartiles a second time for one page -- and would let the two blocks disagree by running
    against two different reads of the same data.
    """
    everyone, population = _workspaces(session, assignment)

    marks = [m for m in (final_marks(session, w) for w in population) if m is not None]
    concepts = rank_concepts(marks, _component_tags(session))
    # Block B's population is cohort_diagnostics' -- every live workspace with a run, broader
    # than Block A's submitted-only. Deliberate: a count does not dilute the way a rate does, so
    # there is no reason to narrow it, and narrowing would change an existing section's numbers.
    cohort = diagnostics if diagnostics is not None else cohort_diagnostics(session, assignment)
    groups = group_mistakes(list(cohort.signatures), _signature_tags(session))
    return MasteryReport(
        submitted=len(population),
        total=len(everyone),
        needs_support=sum(1 for m in marks if m.percent < SUPPORT_THRESHOLD),
        concepts=concepts,
        weakest=weakest_concept(concepts),
        mistakes=groups,
        top_mistake=top_mistake(groups),
    )


@dataclass(frozen=True)
class ConceptMistakes:
    """One concept's detected misconceptions, ranked by how many students made each.

    No aggregate student count: summing the signatures would double-count a student who triggered
    two of them, and there is no cheap way to count distinct students across signatures from the
    counts alone. The group is ranked by its highest single count instead, and the numbers stay on
    the signatures where they are true.
    """

    key: str
    label: str
    mistakes: tuple[SignatureCount, ...]

    @property
    def highest(self) -> int:
        return max((m.students for m in self.mistakes), default=0)


@dataclass(frozen=True)
class StudentRef:
    workspace_public_id: str
    name: str


@dataclass(frozen=True)
class StudentMark:
    student: StudentRef
    points: float
    max_points: float

    @property
    def percent(self) -> float:
        return 100 * self.points / self.max_points if self.max_points else 0.0


@dataclass(frozen=True)
class SignatureStudents:
    signature_key: str
    label: str
    students: tuple[StudentRef, ...]


@dataclass(frozen=True)
class ConceptDetail:
    key: str
    label: str
    group: str
    marks: tuple[StudentMark, ...] = ()
    mistakes: tuple[SignatureStudents, ...] = ()
    clear: tuple[StudentRef, ...] = ()


def group_mistakes(counts: list, tags: dict[str, tuple[str, str]]) -> tuple[ConceptMistakes, ...]:
    """Group detected signatures under their concept, ranked by headcount.

    A signature with no tag is dropped: it is a mistake no concept can be named for, and this
    block is organised by concept. The guard in tests/guards/test_concept_tags.py is what keeps
    that from being a silent gap for a real pack.

    A signature nobody triggered is dropped too. ``cohort_diagnostics`` seeds every signature the
    pack declares at zero, so its whole catalogue arrives whether or not anybody made the mistake.
    """
    grouped: dict[str, list[SignatureCount]] = {}
    labels: dict[str, str] = {}
    for count in counts:
        if count.students <= 0:
            continue
        tag = tags.get(count.key)
        if tag is None:
            continue
        concept_key, concept_label = tag
        labels[concept_key] = concept_label
        grouped.setdefault(concept_key, []).append(count)

    groups = [
        ConceptMistakes(
            key=key,
            label=labels[key],
            mistakes=tuple(sorted(found, key=lambda m: (-m.students, m.key))),
        )
        for key, found in grouped.items()
    ]
    groups.sort(key=lambda g: (-g.highest, g.key))
    return tuple(groups)


def top_mistake(groups: tuple[ConceptMistakes, ...]) -> SignatureCount | None:
    """The single most common misconception across every concept, for the callout."""
    everything = [m for group in groups for m in group.mistakes]
    if not everything:
        return None
    return max(everything, key=lambda m: (m.students, m.key))


def _signature_tags(session) -> dict[str, tuple[str, str]]:
    rows = session.execute(
        db.select(ConceptTag.artifact_key, Concept.key, Concept.label)
        .join(Concept, ConceptTag.concept_id == Concept.id)
        .where(ConceptTag.artifact_kind == KIND_SIGNATURE, Concept.retired_at.is_(None))
    ).all()
    return {artifact_key: (key, label) for artifact_key, key, label in rows}


def _live_concept(session, concept_key: str) -> Concept:
    concept = session.scalars(
        db.select(Concept).where(Concept.key == concept_key, Concept.retired_at.is_(None))
    ).first()
    if concept is None:
        raise LookupError(concept_key)
    return concept


def _student_ref(session, workspace) -> StudentRef:
    student = session.get(User, workspace.student_id)
    name = " ".join(
        part for part in ((student.given_name or ""), (student.family_name or "")) if part
    ).strip() if student else ""
    return StudentRef(workspace_public_id=workspace.public_id,
                      name=name or (student.email if student else workspace.public_id))


def concept_detail(session, assignment, concept_key: str) -> ConceptDetail:
    """Who is behind one concept. Raises ``LookupError`` for an unknown or retired concept, which
    the view turns into ``abort(404)``.

    Two shapes, because the groups carry different evidence. A process concept has marks per
    student. A topic concept has a boolean per student per signature -- so there is nothing to
    average, and the students with nothing detected are listed rather than scored, because
    detection bails entirely on empty books and silence is not understanding.
    """
    concept = _live_concept(session, concept_key)
    everyone, population = _workspaces(session, assignment)

    if concept.group == GROUP_PROCESS:
        keys = {artifact for artifact, (ckey, _l) in _component_tags(session).items()
                if ckey == concept_key}
        marks = []
        for workspace in population:
            final = final_marks(session, workspace)
            if final is None:
                continue
            parts = [c for c in final.components if c.key in keys]
            if not parts:
                continue
            marks.append(StudentMark(
                student=_student_ref(session, workspace),
                points=sum(c.points for c in parts),
                max_points=sum(c.max_points for c in parts),
            ))
        marks.sort(key=lambda m: (m.percent, m.student.workspace_public_id))
        return ConceptDetail(key=concept.key, label=concept.label, group=concept.group,
                             marks=tuple(marks))

    wanted = {artifact for artifact, (ckey, _l) in _signature_tags(session).items()
              if ckey == concept_key}
    by_signature: dict[str, list[StudentRef]] = {}
    labels: dict[str, str] = {}
    clear: list[StudentRef] = []
    # The topic shape walks EVERYONE with a run, not the submitted population: that is the
    # population Block B's counts come from, and a count you can click has to list the people it
    # counted. Narrowing here would show four names under a heading that said six, with nothing
    # on either page saying where the other two went.
    for workspace in everyone:
        run = latest_run(session, workspace)
        if run is None:
            continue
        # Confident detections only, because that is the tally group_mistakes reads
        # (cohort_diagnostics splits them). A balance-only "possible" listed here as a fact would
        # put more names on the page than the count that led to it.
        found = [s for s in run.result.signatures if s.key in wanted and s.confident]
        ref = _student_ref(session, workspace)
        if not found:
            clear.append(ref)
            continue
        for signature in found:
            labels[signature.key] = signature.label
            by_signature.setdefault(signature.key, []).append(ref)

    mistakes = tuple(sorted(
        (SignatureStudents(signature_key=key, label=labels[key], students=tuple(refs))
         for key, refs in by_signature.items()),
        key=lambda s: (-len(s.students), s.signature_key),
    ))
    return ConceptDetail(key=concept.key, label=concept.label, group=concept.group,
                         mistakes=mistakes, clear=tuple(clear))
