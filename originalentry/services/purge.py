"""Retention purge (OPS-7, T11 FERPA).

Hard-deletes a section's work, grades, activity, overrides, enrolments and any users left without
an enrolment, then records a ``staff_action`` summary that holds only counts — no name, email or
figure. Runs after the institution's retention period, through the direct endpoint (the CLI). This
is the only hard delete besides the login-token purge.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import (
    ActivityEvent,
    Assignment,
    AssignmentChoice,
    CheckpointAttempt,
    Disposition,
    Enrollment,
    EntryLine,
    GradeComment,
    GradeOverride,
    GradeRun,
    JournalEntry,
    JournalEntryRevision,
    LoginToken,
    PostingRun,
    PostingRunEntry,
    Section,
    SectionPackAvailability,
    StatementDraft,
    StatementLine,
    User,
    Workspace,
)
from . import staff_actions


@dataclass
class PurgeSummary:
    section_id: int
    assignments: int
    workspaces: int
    students_removed: int


def purge_section(session: Session, section: Section, actor=None) -> PurgeSummary:
    assignment_ids = list(
        session.scalars(select(Assignment.id).where(Assignment.section_id == section.id))
    )
    student_ids = list(
        session.scalars(select(Enrollment.user_id).where(Enrollment.section_id == section.id))
    )
    workspace_ids = list(
        session.scalars(
            select(Workspace.id).where(Workspace.assignment_id.in_(assignment_ids or [0]))
        )
    ) if assignment_ids else []

    def _del(stmt):
        session.execute(stmt)

    if workspace_ids:
        entry_ids_subq = select(JournalEntry.id).where(
            JournalEntry.workspace_id.in_(workspace_ids)
        )
        run_ids_subq = select(PostingRun.id).where(PostingRun.workspace_id.in_(workspace_ids))
        draft_ids_subq = select(StatementDraft.id).where(
            StatementDraft.workspace_id.in_(workspace_ids)
        )
        _del(delete(EntryLine).where(EntryLine.workspace_id.in_(workspace_ids)))
        _del(delete(JournalEntryRevision).where(
            JournalEntryRevision.entry_id.in_(entry_ids_subq)))
        _del(delete(PostingRunEntry).where(PostingRunEntry.posting_run_id.in_(run_ids_subq)))
        _del(delete(PostingRun).where(PostingRun.workspace_id.in_(workspace_ids)))
        _del(delete(Disposition).where(Disposition.workspace_id.in_(workspace_ids)))
        _del(delete(CheckpointAttempt).where(CheckpointAttempt.workspace_id.in_(workspace_ids)))
        # activity_event is the student's own PII-light telemetry and goes with the workspace.
        # audit_log is deliberately NOT purged here: it is the durable, actor-attributed trail of
        # privileged actions and sign-ins, and an audit record that vanished with the data it was
        # meant to hold someone accountable for would be no audit record at all. It carries no
        # workspace_id, so it is out of this delete by construction; this note is why.
        _del(delete(ActivityEvent).where(ActivityEvent.workspace_id.in_(workspace_ids)))
        _del(delete(StatementLine).where(StatementLine.draft_id.in_(draft_ids_subq)))
        _del(delete(StatementDraft).where(StatementDraft.workspace_id.in_(workspace_ids)))
        _del(delete(GradeOverride).where(GradeOverride.workspace_id.in_(workspace_ids)))
        _del(delete(GradeComment).where(GradeComment.workspace_id.in_(workspace_ids)))
        _del(delete(GradeRun).where(GradeRun.workspace_id.in_(workspace_ids)))
        _del(delete(JournalEntry).where(JournalEntry.workspace_id.in_(workspace_ids)))
        _del(delete(Workspace).where(Workspace.id.in_(workspace_ids)))

    if assignment_ids:
        _del(delete(AssignmentChoice).where(AssignmentChoice.assignment_id.in_(assignment_ids)))
        _del(delete(Assignment).where(Assignment.id.in_(assignment_ids)))

    _del(delete(SectionPackAvailability).where(
        SectionPackAvailability.section_id == section.id))
    _del(delete(LoginToken).where(LoginToken.join_section_id == section.id))
    _del(delete(Enrollment).where(Enrollment.section_id == section.id))

    # Students left without any enrolment anywhere are removed (and their tokens).
    removed = 0
    for user_id in student_ids:
        still = session.scalars(
            select(Enrollment).where(Enrollment.user_id == user_id).limit(1)
        ).one_or_none()
        if still is None:
            user = session.get(User, user_id)
            if user is not None and user.role == "student":
                _del(delete(LoginToken).where(LoginToken.user_id == user_id))
                session.delete(user)
                removed += 1

    summary = PurgeSummary(
        section_id=section.id,
        assignments=len(assignment_ids),
        workspaces=len(workspace_ids),
        students_removed=removed,
    )
    staff_actions.record(
        session, actor, "purge_section", "section", section.id,
        detail={"assignments": summary.assignments, "workspaces": summary.workspaces,
                "students_removed": summary.students_removed},
    )
    session.flush()
    return summary
