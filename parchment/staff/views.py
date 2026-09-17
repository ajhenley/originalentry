"""Console screens (I2). Assignments and Progress so far.

Every screen answers a question of one shape: *which students misunderstand what, and where is
each of them now?* Nothing here writes to a student's books.
"""

from __future__ import annotations

from flask import Blueprint, abort, render_template

from ..decorators_staff import staff_view
from ..extensions import db
from ..models import Assignment, ContentPack, PackVersion, Section, Workspace
from ..services.progress import assignment_progress

bp = Blueprint("staff", __name__, url_prefix="/staff")


def _assignment_or_404(public_id: str) -> Assignment:
    assignment = db.session.execute(
        db.select(Assignment).filter_by(public_id=public_id, archived_at=None)
    ).scalar_one_or_none()
    if assignment is None:
        abort(404)
    return assignment


@bp.get("/")
@staff_view
def index():
    rows = db.session.execute(
        db.select(Assignment, Section, ContentPack)
        .join(Section, Assignment.section_id == Section.id)
        .outerjoin(PackVersion, Assignment.fixed_pack_version_id == PackVersion.id)
        .outerjoin(ContentPack, PackVersion.content_pack_id == ContentPack.id)
        .where(Assignment.archived_at.is_(None))
        .order_by(Section.name, Assignment.title)
    ).all()

    counts = dict(
        db.session.execute(
            db.select(Workspace.assignment_id, db.func.count())
            .where(Workspace.archived_at.is_(None))
            .group_by(Workspace.assignment_id)
        ).all()
    )

    assignments = [
        {
            "public_id": assignment.public_id,
            "title": assignment.title,
            "section_name": section.name,
            "company_name": pack.company_name if pack else "—",
            "mode": assignment.mode,
            "due_at": assignment.due_at,
            "students": counts.get(assignment.id, 0),
        }
        for assignment, section, pack in rows
    ]
    return render_template("staff/assignments.html", assignments=assignments)


@bp.get("/progress/<assignment>")
@staff_view
def progress(assignment: str):
    found = _assignment_or_404(assignment)
    section = db.session.get(Section, found.section_id)
    pack_version = (
        db.session.get(PackVersion, found.fixed_pack_version_id)
        if found.fixed_pack_version_id
        else None
    )
    company = (
        db.session.get(ContentPack, pack_version.content_pack_id) if pack_version else None
    )
    return render_template(
        "staff/progress.html",
        assignment=found,
        section=section,
        company_slug=company.slug if company else None,
        rows=assignment_progress(db.session, found),
    )
