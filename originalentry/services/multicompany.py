"""Multi-company: which companies a section may use, and a student choosing one (M1.4, M2.3,
tension 4).

Availability is checked only when a workspace is created or a company is chosen — never mid-work.
Withdrawing a company therefore stops new workspaces without disturbing the ones already open,
and those keep working and stay gradable (A22). Every workspace pins its pack version and variant
at creation (D6 rule 4), so two companies never reach into each other (A20/A23).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    AssignmentChoice,
    ContentPack,
    PackVersion,
    SectionPackAvailability,
    Workspace,
)
from . import staff_actions
from .assignments import variant_for

STATUS_AVAILABLE = "available"
STATUS_WITHDRAWN = "withdrawn"


class ChoiceRefused(Exception):
    """A company a student may not open right now. ``message`` is finished text."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


# ── availability (staff) ─────────────────────────────────────────────────────────────────

def set_availability(
    session: Session, *, section_id: int, content_pack_id: int, available: bool, actor=None
) -> SectionPackAvailability:
    row = session.scalars(
        select(SectionPackAvailability).where(
            SectionPackAvailability.section_id == section_id,
            SectionPackAvailability.content_pack_id == content_pack_id,
        )
    ).one_or_none()
    status = STATUS_AVAILABLE if available else STATUS_WITHDRAWN
    if row is None:
        row = SectionPackAvailability(
            section_id=section_id, content_pack_id=content_pack_id, status=status
        )
        session.add(row)
    else:
        row.status = status
    session.flush()
    staff_actions.record(
        session, actor, "set_availability", "section_pack_availability", row.id,
        detail={"section": section_id, "content_pack": content_pack_id, "status": status},
    )
    return row


def available_content_pack_ids(session: Session, section_id: int) -> set[int]:
    return set(
        session.scalars(
            select(SectionPackAvailability.content_pack_id).where(
                SectionPackAvailability.section_id == section_id,
                SectionPackAvailability.status == STATUS_AVAILABLE,
            )
        )
    )


def is_available(session: Session, section_id: int, content_pack_id: int) -> bool:
    return content_pack_id in available_content_pack_ids(session, section_id)


# ── choice (assignment) ──────────────────────────────────────────────────────────────────

def add_assignment_choice(session: Session, *, assignment_id: int, pack_version_id: int) -> None:
    exists = session.scalars(
        select(AssignmentChoice).where(
            AssignmentChoice.assignment_id == assignment_id,
            AssignmentChoice.pack_version_id == pack_version_id,
        )
    ).one_or_none()
    if exists is None:
        session.add(
            AssignmentChoice(assignment_id=assignment_id, pack_version_id=pack_version_id)
        )
        session.flush()


@dataclass(frozen=True)
class CompanyOption:
    pack_version_id: int
    content_pack_id: int
    slug: str
    name: str
    accent_hex: str
    monogram: str
    available: bool


def company_options(session: Session, assignment) -> list[CompanyOption]:
    """The companies offered for a choice assignment, each flagged with whether the section may
    still open it (a withdrawn one is shown but cannot be chosen)."""
    available = available_content_pack_ids(session, _section_id_of(session, assignment))
    rows = session.execute(
        select(PackVersion, ContentPack)
        .join(ContentPack, PackVersion.content_pack_id == ContentPack.id)
        .join(AssignmentChoice, AssignmentChoice.pack_version_id == PackVersion.id)
        .where(AssignmentChoice.assignment_id == assignment.id)
        .order_by(ContentPack.company_name)
    ).all()
    return [
        CompanyOption(
            pack_version_id=pv.id,
            content_pack_id=cp.id,
            slug=cp.slug,
            name=cp.company_name,
            accent_hex=pv.accent_hex,
            monogram=pv.monogram,
            available=cp.id in available,
        )
        for pv, cp in rows
    ]


ALREADY_STARTED = (
    "You have already recorded work in this company, so it is yours for this assignment. "
    "If you started in the wrong one, your instructor can give you a fresh set of books."
)


def has_started(session: Session, workspace: Workspace) -> bool:
    """Whether anything has been recorded in these books (M2.4).

    Triage counts. Deciding a document needs no entry is a judgement the student made about this
    company's papers, and it is exactly the work the first component is marked on.
    """
    from ..models import CheckpointAttempt, Disposition, JournalEntry, StatementDraft

    for model in (JournalEntry, Disposition, StatementDraft, CheckpointAttempt):
        started = session.execute(
            select(model.id).where(model.workspace_id == workspace.id).limit(1)
        ).first()
        if started is not None:
            return True
    return False


def choose_company(session: Session, assignment, student, *, pack_version_id: int) -> Workspace:
    """Open a student's books on the company they picked (M2.3, M2.4).

    The choice is recorded, and it locks at the **first entry** rather than at the moment of
    choosing. A student who clicks the wrong company and has recorded nothing can put it right
    themselves; once they have recorded anything, the books are theirs for this assignment and
    only an instructor can give them a fresh set (I1.12).
    """
    existing = session.scalars(
        select(Workspace).where(
            Workspace.assignment_id == assignment.id,
            Workspace.student_id == student.id,
            Workspace.archived_at.is_(None),
        )
    ).one_or_none()
    if existing is not None and existing.pack_version_id == pack_version_id:
        return existing  # the same company again changes nothing
    if existing is not None and has_started(session, existing):
        raise ChoiceRefused(ALREADY_STARTED)

    allowed = {o.pack_version_id: o for o in company_options(session, assignment)}
    option = allowed.get(pack_version_id)
    if option is None:
        raise ChoiceRefused("That company is not one this assignment offers.")
    if not option.available:
        raise ChoiceRefused("That company is not open for your section right now.")

    if existing is not None:
        # Empty books, pointed at another company. Nothing is scoped to the old pack version yet,
        # which is precisely why this is safe before the first entry and refused after it.
        existing.pack_version_id = pack_version_id
        existing.variant_id = variant_for(session, assignment, pack_version_id)
        existing.company_chosen_at = datetime.now(UTC)
        session.flush()
        return existing

    workspace = Workspace(
        assignment_id=assignment.id,
        student_id=student.id,
        pack_version_id=pack_version_id,
        variant_id=variant_for(session, assignment, pack_version_id),
        status="not_started",
        company_chosen_at=datetime.now(UTC),
    )
    session.add(workspace)
    session.flush()
    return workspace


def _section_id_of(session: Session, assignment) -> int:
    return assignment.section_id
