"""Cohort diagnostics (I4.1–I4.3, I4.5).

This is the screen the paper set could never provide: which designed errors a section actually
made, which documents were most often handled differently from the key, and how long the work
took. It reports facts about a cohort — counts, medians, documents — and names no student as
having done anything wrong (T8.8).

Everything is read from what grading already stored, plus the activity log. Nothing is recomputed
here, so the numbers on this screen are the numbers the instructor saw when marking.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..grading.time_on_task import minutes_from, quartiles
from ..models import (
    ActivityEvent,
    AnswerKey,
    Assignment,
    Disposition,
    SourceDocument,
    User,
    Variant,
    Workspace,
)
from ..packs import schema
from ..workspaces import class_workspaces
from .grades import active_overrides, from_hundredths, latest_run

BUCKET_HOURS = (1, 2, 4, 8, 12)


@dataclass(frozen=True)
class SignatureCount:
    key: str
    label: str
    students: int  # recognised from the entry for one document
    possible: int  # recognised only from the balances, so reported as a possibility


@dataclass(frozen=True)
class TriageCount:
    document_ref: str
    recorded_when_none_is_expected: int
    no_entry_when_one_is_expected: int
    not_handled: int

    @property
    def total(self) -> int:
        return (
            self.recorded_when_none_is_expected
            + self.no_entry_when_one_is_expected
            + self.not_handled
        )


@dataclass(frozen=True)
class TimeOnTask:
    students: int
    median_minutes: float
    lower_quartile: float
    upper_quartile: float
    buckets: tuple[tuple[str, int], ...] = ()


@dataclass
class CohortDiagnostics:
    total: int
    graded: int
    signatures: tuple[SignatureCount, ...] = ()
    triage: tuple[TriageCount, ...] = ()
    time_on_task: TimeOnTask = field(
        default_factory=lambda: TimeOnTask(0, 0.0, 0.0, 0.0, ())
    )


def cohort_diagnostics(session: Session, assignment: Assignment) -> CohortDiagnostics:
    workspaces = _workspaces(session, assignment)
    keys = _keys_by_variant(session, assignment)

    graded = 0
    signature_hits: dict[str, list[int]] = {}
    labels: dict[str, str] = {}
    for key in keys.values():
        for signature in key.error_signatures:
            labels[signature.key] = signature.label
            signature_hits.setdefault(signature.key, [0, 0])

    for workspace in workspaces:
        run = latest_run(session, workspace)
        if run is None:
            continue
        graded += 1
        for found in run.result.signatures:
            counts = signature_hits.setdefault(found.key, [0, 0])
            labels.setdefault(found.key, found.label)
            counts[0 if found.confident else 1] += 1

    signatures = tuple(
        SignatureCount(key=key, label=labels.get(key, key), students=counts[0],
                       possible=counts[1])
        for key, counts in sorted(
            signature_hits.items(), key=lambda item: (-item[1][0], item[0])
        )
    )

    return CohortDiagnostics(
        total=len(workspaces),
        graded=graded,
        signatures=signatures,
        triage=_triage_counts(session, assignment, workspaces, keys),
        time_on_task=_time_on_task(session, workspaces),
    )


def cohort_csv(session: Session, assignment: Assignment):
    """One row per student, for the instructor's own analysis (I4.5).

    The header is stable so a spreadsheet built on last term's export still opens this one.
    """
    workspaces = _workspaces(session, assignment)
    component_keys: list[str] = []
    for workspace in workspaces:
        run = latest_run(session, workspace)
        if run is not None:
            component_keys = [c.key for c in run.result.components]
            break

    header = [
        "email", "family_name", "given_name", "variant", "submission_status",
        "total_points", "max_points", "percent", "needs_review", "time_on_task_minutes",
        *component_keys,
        "signatures",
    ]
    yield header

    minutes = _minutes_by_workspace(session, workspaces)
    variants = _variant_codes(session, assignment)

    for workspace in workspaces:
        student = session.get(User, workspace.student_id)
        run = latest_run(session, workspace)
        overrides = active_overrides(session, workspace)
        if run is None:
            yield [
                student.email, student.family_name, student.given_name,
                variants.get(workspace.variant_id, ""), "", "", "", "", "",
                f"{minutes.get(workspace.id, 0):.0f}",
                *["" for _ in component_keys], "",
            ]
            continue

        points = {c.key: c.points for c in run.result.components}
        for key, override in overrides.items():
            points[key] = from_hundredths(override.points)
        total = sum(points.values())
        maximum = sum(c.max_points for c in run.result.components)
        yield [
            student.email,
            student.family_name,
            student.given_name,
            variants.get(workspace.variant_id, ""),
            run.submission_status,
            f"{total:.2f}",
            f"{maximum:.2f}",
            f"{(100 * total / maximum if maximum else 0):.1f}",
            "yes" if run.needs_review else "no",
            f"{minutes.get(workspace.id, 0):.0f}",
            *[f"{points.get(key, 0):.2f}" for key in component_keys],
            "; ".join(s.label for s in run.result.signatures),
        ]


def _workspaces(session: Session, assignment: Assignment) -> list[Workspace]:
    """The cohort this screen reports on: every live workspace but the teacher's own practice
    copy, which would show up here as an extra student who made the designed errors on purpose."""
    return class_workspaces(session, assignment)


def _keys_by_variant(session: Session, assignment: Assignment) -> dict[int, schema.AnswerKey]:
    if assignment.fixed_pack_version_id is None:
        return {}
    rows = session.execute(
        select(AnswerKey.variant_id, AnswerKey.payload).where(
            AnswerKey.pack_version_id == assignment.fixed_pack_version_id
        )
    ).all()
    return {variant_id: schema.load_answer_key(payload) for variant_id, payload in rows}


def _variant_codes(session: Session, assignment: Assignment) -> dict[int, str]:
    if assignment.fixed_pack_version_id is None:
        return {}
    return dict(
        session.execute(
            select(Variant.id, Variant.code).where(
                Variant.pack_version_id == assignment.fixed_pack_version_id
            )
        ).all()
    )


def _triage_counts(
    session: Session, assignment: Assignment, workspaces: list[Workspace], keys
) -> tuple[TriageCount, ...]:
    if not workspaces or assignment.fixed_pack_version_id is None:
        return ()

    refs = dict(
        session.execute(
            select(SourceDocument.id, SourceDocument.ref).where(
                SourceDocument.pack_version_id == assignment.fixed_pack_version_id
            )
        ).all()
    )
    chosen: dict[int, dict[str, str]] = {ws.id: {} for ws in workspaces}
    for workspace_id, document_id, choice in session.execute(
        select(Disposition.workspace_id, Disposition.document_id, Disposition.choice).where(
            Disposition.workspace_id.in_([ws.id for ws in workspaces]),
            Disposition.superseded_at.is_(None),
        )
    ):
        if document_id in refs:
            chosen[workspace_id][refs[document_id]] = choice

    tallies: dict[str, list[int]] = {}
    for workspace in workspaces:
        key = keys.get(workspace.variant_id)
        if key is None:
            continue
        for ref, requires_entry in key.triage.items():
            counts = tallies.setdefault(ref, [0, 0, 0])
            choice = chosen[workspace.id].get(ref)
            if choice is None:
                counts[2] += 1
            elif choice == "record" and not requires_entry:
                counts[0] += 1
            elif choice == "no_entry" and requires_entry:
                counts[1] += 1

    rows = [
        TriageCount(document_ref=ref, recorded_when_none_is_expected=counts[0],
                    no_entry_when_one_is_expected=counts[1], not_handled=counts[2])
        for ref, counts in tallies.items()
    ]
    rows.sort(key=lambda row: (-(row.recorded_when_none_is_expected
                                 + row.no_entry_when_one_is_expected), row.document_ref))
    return tuple(rows)


def _minutes_by_workspace(session: Session, workspaces: list[Workspace]) -> dict[int, float]:
    if not workspaces:
        return {}
    times: dict[int, list] = {ws.id: [] for ws in workspaces}
    for workspace_id, at in session.execute(
        select(ActivityEvent.workspace_id, ActivityEvent.at).where(
            ActivityEvent.workspace_id.in_(list(times))
        )
    ):
        times[workspace_id].append(at)
    return {workspace_id: minutes_from(stamps) for workspace_id, stamps in times.items()}


def _time_on_task(session: Session, workspaces: list[Workspace]) -> TimeOnTask:
    minutes = _minutes_by_workspace(session, workspaces)
    values = [value for value in minutes.values()]
    lower, middle, upper = quartiles(values)

    buckets: list[tuple[str, int]] = []
    previous = 0
    for hours in BUCKET_HOURS:
        buckets.append((
            f"{previous}–{hours} h",
            sum(1 for value in values if previous * 60 <= value < hours * 60),
        ))
        previous = hours
    buckets.append((
        f"{previous} h and over", sum(1 for value in values if value >= previous * 60)
    ))

    return TimeOnTask(
        students=len(values),
        median_minutes=middle,
        lower_quartile=lower,
        upper_quartile=upper,
        buckets=tuple(buckets),
    )
