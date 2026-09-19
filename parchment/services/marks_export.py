"""Marks export (I5.1). Two presets — Generic and Canvas-style — both carrying ``late_hours`` and
``submission_status``. The app computes no penalty; the numbers are the released marks and the
facts about how the work stood (tension 10)."""

from __future__ import annotations

import csv
import io

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Assignment, Enrollment, User, Workspace
from .grades import final_marks, submission_status

GENERIC = "generic"
CANVAS = "canvas"


def _rows(session: Session, assignment: Assignment):
    workspaces = session.scalars(
        select(Workspace)
        .where(Workspace.assignment_id == assignment.id, Workspace.archived_at.is_(None))
        .order_by(Workspace.id)
    ).all()
    for ws in workspaces:
        student = session.get(User, ws.student_id)
        enrolment = session.scalars(
            select(Enrollment).where(
                Enrollment.section_id == assignment.section_id,
                Enrollment.user_id == ws.student_id,
            )
        ).one_or_none()
        marks = final_marks(session, ws)
        yield {
            "name": f"{student.given_name} {student.family_name}".strip() or student.email,
            "email": student.email,
            "student_number": (enrolment.student_number if enrolment else "") or "",
            "points": round(marks.total_points, 2) if marks else "",
            "max_points": round(marks.max_points, 2) if marks else "",
            "percent": round(marks.percent, 1) if marks else "",
            "late_hours": ws.submitted_late_hours or 0,
            "submission_status": submission_status(session, ws),
        }


def marks_csv(session: Session, assignment: Assignment, preset: str = GENERIC) -> str:
    buffer = io.StringIO()
    rows = list(_rows(session, assignment))

    if preset == CANVAS:
        # Canvas gradebook import: one score column named for the assignment, plus our two facts.
        header = ["Student", "SIS Login ID", assignment.title, "late_hours", "submission_status"]
        writer = csv.writer(buffer)
        writer.writerow(header)
        for r in rows:
            writer.writerow([r["name"], r["email"], r["percent"],
                             r["late_hours"], r["submission_status"]])
    else:
        fields = ["name", "email", "student_number", "points", "max_points", "percent",
                  "late_hours", "submission_status"]
        writer = csv.DictWriter(buffer, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    return buffer.getvalue()
