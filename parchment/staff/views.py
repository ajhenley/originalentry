"""Console screens (I2). Assignments and Progress so far.

Every screen answers a question of one shape: *which students misunderstand what, and where is
each of them now?* Nothing here writes to a student's books.
"""

from __future__ import annotations

import csv
import io

from flask import (
    Blueprint,
    Response,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user

from ..decorators_staff import staff_view
from ..extensions import db
from ..models import Assignment, ContentPack, PackVersion, Section, User, Workspace
from ..services import staff_actions
from ..services.diagnostics import cohort_csv, cohort_diagnostics
from ..services.grades import (
    final_marks,
    grade_section,
    latest_run,
    release_marks,
    set_comment,
    set_override,
)
from ..services.progress import assignment_progress

BATCH = 10  # workspaces graded per request, so nothing comes near the request limit (I3.7)

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


# ── Grading (I3) ─────────────────────────────────────────────────────────────────────────

def _workspace_or_404(assignment: Assignment, public_id: str) -> Workspace:
    workspace = db.session.execute(
        db.select(Workspace).filter_by(public_id=public_id, assignment_id=assignment.id,
                                       archived_at=None)
    ).scalar_one_or_none()
    if workspace is None:
        abort(404)
    return workspace


@bp.get("/grading/<assignment>")
@staff_view
def grading(assignment: str):
    found = _assignment_or_404(assignment)
    only_review = request.args.get("filter") == "review"

    rows = []
    for workspace, student in db.session.execute(
        db.select(Workspace, User)
        .join(User, Workspace.student_id == User.id)
        .where(Workspace.assignment_id == found.id, Workspace.archived_at.is_(None))
        .order_by(User.email)
    ).all():
        marks = final_marks(db.session, workspace)
        if only_review and not (marks and marks.needs_review):
            continue
        run = latest_run(db.session, workspace)
        rows.append({
            "workspace_public_id": workspace.public_id,
            "student_name": f"{student.given_name} {student.family_name}".strip()
            or student.email,
            "student_email": student.email,
            "marks": marks,
            "submission_status": run.submission_status if run else None,
            "graded_at": run.created_at if run else None,
        })

    return render_template(
        "staff/grading.html",
        assignment=found,
        section=db.session.get(Section, found.section_id),
        rows=rows,
        only_review=only_review,
        released=found.marks_released_at is not None,
    )


@bp.post("/grading/<assignment>/run")
@staff_view
def grading_run(assignment: str):
    found = _assignment_or_404(assignment)
    graded, total = grade_section(db.session, found, actor=current_user, limit=BATCH)
    staff_actions.record(db.session, current_user, staff_actions.GRADE_RUN, "assignment",
                         found.id, detail={"graded": len(graded), "of": total})
    db.session.commit()
    flash(f"Graded {len(graded)} of {total}.")
    return redirect(url_for("staff.grading", assignment=found.public_id))


@bp.post("/grading/<assignment>/release")
@staff_view
def grading_release(assignment: str):
    found = _assignment_or_404(assignment)
    release_marks(db.session, found, actor=current_user)
    staff_actions.record(db.session, current_user, staff_actions.RELEASE_MARKS, "assignment",
                         found.id)
    db.session.commit()
    flash("Marks released to this section.")
    return redirect(url_for("staff.grading", assignment=found.public_id))


@bp.get("/grading/<assignment>/<workspace>")
@staff_view
def grading_detail(assignment: str, workspace: str):
    found = _assignment_or_404(assignment)
    ws = _workspace_or_404(found, workspace)
    student = db.session.get(User, ws.student_id)
    run = latest_run(db.session, ws)
    company = None
    pack_version = db.session.get(PackVersion, ws.pack_version_id)
    if pack_version is not None:
        company = db.session.get(ContentPack, pack_version.content_pack_id)
    return render_template(
        "staff/grading_detail.html",
        assignment=found,
        workspace=ws,
        company_slug=company.slug if company else None,
        student_name=f"{student.given_name} {student.family_name}".strip() or student.email,
        marks=final_marks(db.session, ws),
        run=run,
        result=run.result if run else None,
    )


@bp.post("/grading/<assignment>/<workspace>/override")
@staff_view
def grading_override(assignment: str, workspace: str):
    found = _assignment_or_404(assignment)
    ws = _workspace_or_404(found, workspace)
    back = redirect(url_for("staff.grading_detail", assignment=found.public_id,
                            workspace=ws.public_id))

    component_key = (request.form.get("component_key") or "").strip()
    reason = (request.form.get("reason") or "").strip()
    try:
        points = float(request.form.get("points") or "")
    except ValueError:
        flash("Enter the marks as a number, for example 8 or 8.5.")
        return back

    try:
        set_override(db.session, ws, component_key, points, reason, actor=current_user)
    except ValueError as refused:
        flash(str(refused))
        return back

    staff_actions.record(db.session, current_user, staff_actions.GRADE_OVERRIDE, "workspace",
                         ws.id, reason=reason, detail={"component": component_key,
                                                       "points": points})
    db.session.commit()
    flash(f"{component_key} marked by hand.")
    return back


@bp.post("/grading/<assignment>/<workspace>/comment")
@staff_view
def grading_comment(assignment: str, workspace: str):
    found = _assignment_or_404(assignment)
    ws = _workspace_or_404(found, workspace)
    set_comment(db.session, ws, (request.form.get("body") or "").strip(), actor=current_user)
    staff_actions.record(db.session, current_user, staff_actions.GRADE_COMMENT, "workspace", ws.id)
    db.session.commit()
    flash("Comment saved. The student sees it once marks are released.")
    return redirect(url_for("staff.grading_detail", assignment=found.public_id,
                            workspace=ws.public_id))


# ── Diagnostics (I4) ─────────────────────────────────────────────────────────────────────
# The reason to build this rather than keep the paper set: which misconception a cohort actually
# has. It counts, and the instructor draws the conclusion (T8.8).


@bp.get("/diagnostics/<assignment>")
@staff_view
def diagnostics(assignment: str):
    found = _assignment_or_404(assignment)
    return render_template(
        "staff/diagnostics.html",
        assignment=found,
        section=db.session.get(Section, found.section_id),
        diagnostics=cohort_diagnostics(db.session, found),
    )


@bp.get("/diagnostics/<assignment>/export.csv")
@staff_view
def diagnostics_export(assignment: str):
    found = _assignment_or_404(assignment)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    for row in cohort_csv(db.session, found):
        writer.writerow(row)
    filename = f"{found.public_id}-cohort.csv"
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
