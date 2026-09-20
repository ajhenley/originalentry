"""Importing a roster from CSV (I1.5).

The join code is the ordinary way into a section. A roster is for the first day of term, when the
instructor has the registrar's export and forty students who have not been told anything yet.

**Importing an address does not make it anyone's account.** Sign-in is still a link sent to that
address (E2), so an imported row is an enrolment waiting for whoever can read the mail. That is
what makes handing this to an instructor safe, and it is why nothing here sets a password, a
session or a verified flag — there are none to set.

The import is safe to run twice: a student already enrolled is counted and left alone. An
instructor who is not sure whether the first upload worked will run it again, so that has to be
the boring outcome rather than a duplicate or an error.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import ROLE_STUDENT, Enrollment, Section, User
from . import staff_actions
from .assignments import open_workspace

ROSTER = "roster"

# Deliberately loose: this decides whether a *cell* is an address at all, not whether the mail
# will arrive. Anything that gets past it is still only an enrolment until a link is answered.
_ADDRESS = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")

_EMAIL_HEADERS = {"email", "email address", "e-mail", "mail", "username"}
_GIVEN_HEADERS = {"given name", "given_name", "given", "first name", "first_name", "first",
                  "forename"}
_FAMILY_HEADERS = {"family name", "family_name", "family", "last name", "last_name", "last",
                   "surname"}

NO_EMAIL_COLUMN = (
    "This file has no email column. Give it a header row with a column called Email, "
    "and optionally Given name and Family name."
)
NOT_AN_ADDRESS = "Not an email address."
ALREADY_STAFF = "This address belongs to a member of staff."


class RosterRefused(Exception):
    """The file as a whole cannot be read. Individual bad rows are reported, not raised."""


@dataclass
class RosterReport:
    enrolled: int = 0
    already: int = 0
    refused: list[tuple[int, str]] = field(default_factory=list)  # (line number, why)

    @property
    def rows(self) -> int:
        return self.enrolled + self.already + len(self.refused)


def _column_index(header: list[str]) -> tuple[int, int | None, int | None]:
    cleaned = [(cell or "").strip().lower().lstrip("﻿") for cell in header]

    def find(names: set[str]) -> int | None:
        for i, cell in enumerate(cleaned):
            if cell in names:
                return i
        return None

    email = find(_EMAIL_HEADERS)
    if email is None:
        raise RosterRefused(NO_EMAIL_COLUMN)
    return email, find(_GIVEN_HEADERS), find(_FAMILY_HEADERS)


def _cell(row: list[str], index: int | None) -> str:
    if index is None or index >= len(row):
        return ""
    return (row[index] or "").strip()


def import_roster(
    session: Session, *, section: Section, csv_text: str, actor=None
) -> RosterReport:
    """Enrol everyone the file names, and open their books on the assignments already running."""
    reader = csv.reader(io.StringIO(csv_text))
    try:
        header = next(reader)
    except StopIteration as empty:
        raise RosterRefused(NO_EMAIL_COLUMN) from empty

    email_at, given_at, family_at = _column_index(header)
    report = RosterReport()

    for line, row in enumerate(reader, start=2):  # line 1 is the header, as a spreadsheet counts
        if not any((cell or "").strip() for cell in row):
            continue  # a blank line between groups is not a mistake worth reporting
        address = _cell(row, email_at)
        if not _ADDRESS.match(address):
            report.refused.append((line, NOT_AN_ADDRESS))
            continue

        user = session.scalars(
            select(User).where(func.lower(User.email) == address.lower())
        ).one_or_none()
        if user is not None and user.role != ROLE_STUDENT:
            # Never quietly turn a colleague into a student because they appear in a spreadsheet.
            report.refused.append((line, ALREADY_STAFF))
            continue
        if user is None:
            user = User(
                email=address,
                given_name=_cell(row, given_at),
                family_name=_cell(row, family_at),
                role=ROLE_STUDENT,
            )
            session.add(user)
            session.flush()
        # An existing student keeps the name they gave; the registrar's spelling does not win.

        enrolment = session.scalars(
            select(Enrollment).where(Enrollment.section_id == section.id,
                                     Enrollment.user_id == user.id)
        ).one_or_none()
        if enrolment is not None:
            report.already += 1
            continue

        session.add(Enrollment(section_id=section.id, user_id=user.id, source=ROSTER))
        session.flush()
        for assignment in _open_assignments(session, section):
            open_workspace(session, assignment, user)
        report.enrolled += 1

    staff_actions.record(
        session, actor, "import_roster", "section", section.id,
        detail={"enrolled": report.enrolled, "already": report.already,
                "refused": len(report.refused)},
    )
    return report


def _open_assignments(session: Session, section: Section):
    from datetime import UTC, datetime

    from ..models import Assignment

    now = datetime.now(UTC)
    return [
        assignment
        for assignment in session.scalars(
            select(Assignment)
            .where(Assignment.section_id == section.id, Assignment.archived_at.is_(None))
            .order_by(Assignment.id)
        )
        if assignment.opens_at is None or assignment.opens_at <= now
    ]
