"""Setting a term up: sections, assignments, join codes and enrolment (I1.1–I1.6).

An instructor has to be able to start a term without anyone opening a database session. Making a
section hands out a join code; making an assignment names one company from the catalogue; cloning
last term's assignment moves every date by the same offset; and a student who types the code is
enrolled and has their own books, with a variant handed to them on the way in.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    Assignment,
    Enrollment,
    PackVersion,
    Section,
    Variant,
    Workspace,
)
from ..models.work import LATE_ACCEPT, LATE_CLOSED
from . import staff_actions

# No O/0 or I/1: a code is read aloud in a classroom and typed by forty people.
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8

ROUND_ROBIN = "round_robin"
RANDOM = "random"
MANUAL = "manual"


class JoinRefused(Exception):
    """The code is not one in use. The message never says which part was wrong."""

    def __init__(self, message: str = "That code is not in use. Check it with your instructor."):
        super().__init__(message)
        self.message = message


def new_join_code(session: Session) -> str:
    for _ in range(20):
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
        clash = session.scalars(select(Section.id).where(Section.join_code == code)).first()
        if clash is None:
            return code
    raise RuntimeError("could not find an unused join code")


def create_section(session: Session, *, name: str, term: str, course_tag: str | None = None,
                   actor=None) -> Section:
    section = Section(name=name, term=term, course_tag=course_tag,
                      join_code=new_join_code(session))
    session.add(section)
    session.flush()
    staff_actions.record(session, actor, "create_section", "section", section.id)
    return section


def rotate_join_code(session: Session, section: Section, actor=None) -> Section:
    """Hand out a new code and retire the old one — the answer to a code that has got out."""
    section.join_code = new_join_code(session)
    section.join_code_active = True
    session.flush()
    staff_actions.record(session, actor, "rotate_join_code", "section", section.id)
    return section


def create_assignment(
    session: Session,
    *,
    section: Section,
    title: str,
    pack_version: PackVersion | None = None,
    choice_pack_versions: list[PackVersion] | None = None,
    mode: str = "screen",
    due_at: datetime | None = None,
    opens_at: datetime | None = None,
    late_policy: str = LATE_CLOSED,
    late_until: datetime | None = None,
    variant_policy: str = ROUND_ROBIN,
    guided_mode: bool = True,
    actor=None,
) -> Assignment:
    """A fixed assignment names one company (``pack_version``); a choice assignment offers a list
    (``choice_pack_versions``) and the student picks (tension 4). Offered companies are marked
    available to the section so they can be chosen."""
    choices = choice_pack_versions or []
    is_choice = pack_version is None and bool(choices)

    assignment = Assignment(
        section_id=section.id,
        title=title,
        mode=mode,
        company_policy="choice" if is_choice else "fixed",
        fixed_pack_version_id=None if is_choice else pack_version.id,
        variant_policy=variant_policy,
        opens_at=opens_at,
        due_at=due_at,
        late_policy=late_policy,
        late_until=late_until if late_policy == LATE_ACCEPT else None,
        guided_mode=guided_mode,
    )
    session.add(assignment)
    session.flush()

    # Local import: multicompany imports variant_for from this module, so a module-level import
    # would be circular.
    from .multicompany import add_assignment_choice, set_availability

    if is_choice:
        for chosen in choices:
            add_assignment_choice(session, assignment_id=assignment.id,
                                  pack_version_id=chosen.id)
            set_availability(session, section_id=section.id,
                             content_pack_id=chosen.content_pack_id, available=True, actor=actor)
        detail = {"choices": [c.id for c in choices]}
    else:
        set_availability(session, section_id=section.id,
                         content_pack_id=pack_version.content_pack_id, available=True, actor=actor)
        detail = {"pack_version": pack_version.id}

    staff_actions.record(session, actor, "create_assignment", "assignment", assignment.id,
                         detail=detail)
    return assignment


def clone_assignment(
    session: Session,
    assignment: Assignment,
    *,
    section: Section | None = None,
    shift: timedelta = timedelta(),
    title: str | None = None,
    actor=None,
) -> Assignment:
    """Last term's assignment with every date moved by the same offset (I1.6, A14)."""

    def moved(when: datetime | None) -> datetime | None:
        return when + shift if when else None

    clone = Assignment(
        section_id=(section or assignment).id if section else assignment.section_id,
        title=title or assignment.title,
        mode=assignment.mode,
        company_policy=assignment.company_policy,
        fixed_pack_version_id=assignment.fixed_pack_version_id,
        variant_policy=assignment.variant_policy,
        opens_at=moved(assignment.opens_at),
        due_at=moved(assignment.due_at),
        late_policy=assignment.late_policy,
        late_until=moved(assignment.late_until),
        prerequisite_assignment_id=assignment.prerequisite_assignment_id,
        guided_mode=assignment.guided_mode,
        cloned_from_id=assignment.id,
    )
    session.add(clone)
    session.flush()
    staff_actions.record(session, actor, "clone_assignment", "assignment", clone.id,
                         detail={"cloned_from": assignment.id})
    return clone


def join_with_code(session: Session, *, code: str, student) -> list[Workspace]:
    """Enrol a student and open their books on every assignment that has opened (I1.4).

    Joining twice changes nothing: the enrolment and the workspaces they already have stand.
    """
    section = session.scalars(
        select(Section).where(
            Section.join_code == (code or "").strip().upper(),
            Section.join_code_active.is_(True),
            Section.archived_at.is_(None),
        )
    ).one_or_none()
    if section is None:
        raise JoinRefused()

    enrolment = session.scalars(
        select(Enrollment).where(Enrollment.section_id == section.id,
                                 Enrollment.user_id == student.id)
    ).one_or_none()
    if enrolment is None:
        session.add(Enrollment(section_id=section.id, user_id=student.id, source="join_code"))
        session.flush()

    now = datetime.now(UTC)
    workspaces = []
    for assignment in session.scalars(
        select(Assignment)
        .where(Assignment.section_id == section.id, Assignment.archived_at.is_(None))
        .order_by(Assignment.id)
    ):
        if assignment.opens_at is not None and assignment.opens_at > now:
            continue  # enrolled, but the assignment has not opened yet
        workspace = open_workspace(session, assignment, student)
        if workspace is not None:
            workspaces.append(workspace)
    return workspaces


def open_workspace(session: Session, assignment: Assignment, student) -> Workspace | None:
    """One live workspace per student per assignment, with a variant handed out on the way in."""
    existing = session.scalars(
        select(Workspace).where(
            Workspace.assignment_id == assignment.id,
            Workspace.student_id == student.id,
            Workspace.archived_at.is_(None),
        )
    ).one_or_none()
    if existing is not None:
        return existing
    if assignment.fixed_pack_version_id is None:
        return None  # a student-choice assignment waits for the student to choose (M2.3)

    workspace = Workspace(
        assignment_id=assignment.id,
        student_id=student.id,
        pack_version_id=assignment.fixed_pack_version_id,
        variant_id=variant_for(session, assignment, assignment.fixed_pack_version_id),
        status="not_started",
    )
    session.add(workspace)
    session.flush()
    return workspace


def variant_for(session: Session, assignment: Assignment, pack_version_id: int) -> int | None:
    """Hand a variant to a new workspace on ``pack_version_id`` per the assignment's policy. Works
    for the fixed pack version and for a company a student chooses."""
    variants = list(
        session.scalars(
            select(Variant.id)
            .where(Variant.pack_version_id == pack_version_id)
            .order_by(Variant.code)
        )
    )
    if not variants:
        return None
    if assignment.variant_policy == MANUAL:
        return None  # the instructor assigns it before the student can start
    if assignment.variant_policy == RANDOM:
        return secrets.choice(variants)

    taken = session.execute(
        select(func.count()).select_from(Workspace).where(
            Workspace.assignment_id == assignment.id, Workspace.archived_at.is_(None)
        )
    ).scalar_one()
    return variants[taken % len(variants)]
