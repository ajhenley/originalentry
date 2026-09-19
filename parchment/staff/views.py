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
    current_app,
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
from ..models.work import LATE_ACCEPT, LATE_CLOSED
from ..packs.importing import PackImportRefused, import_pack_zip
from ..services import multicompany, staff_actions
from ..services.assignments import (
    clone_assignment,
    create_assignment,
    create_section,
    rotate_join_code,
)
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
            "join_code": section.join_code if section.join_code_active else "—",
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


# ── Setting a term up (I1.1–I1.6) ────────────────────────────────────────────────────────
# An instructor starts a term here, not in a database session: a section with a join code, an
# assignment on a company from the catalogue, and last term's assignment cloned with new dates.


def _catalogue():
    """Every pack version the app holds, newest first, with its company name."""
    rows = db.session.execute(
        db.select(PackVersion, ContentPack)
        .join(ContentPack, PackVersion.content_pack_id == ContentPack.id)
        .order_by(ContentPack.company_name, PackVersion.version.desc())
    ).all()
    return [
        {"id": version.id, "label": f"{pack.company_name} · v{version.version}",
         "company_name": pack.company_name, "has_images": version.has_images}
        for version, pack in rows
    ]


def _parse_when(raw: str | None):
    """A date and time typed on the form, read in the course's own time zone (D1)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    if not (raw or "").strip():
        return None
    try:
        naive = datetime.fromisoformat(raw.strip())
    except ValueError:
        return None
    course_tz = ZoneInfo(current_app.extensions["parchment_config"].COURSE_TZ)
    return naive.replace(tzinfo=course_tz) if naive.tzinfo is None else naive


@bp.get("/assignments/new")
@staff_view
def assignment_new():
    return render_template(
        "staff/assignment_new.html",
        catalogue=_catalogue(),
        sections=db.session.scalars(
            db.select(Section).where(Section.archived_at.is_(None)).order_by(Section.name)
        ).all(),
        values={},
        errors={},
    )


@bp.post("/assignments/new")
@staff_view
def assignment_create():
    catalogue = _catalogue()
    form = request.form
    errors = {}

    title = (form.get("title") or "").strip()
    if not title:
        errors["title"] = "Give the assignment a title."

    pack_version = db.session.get(PackVersion, form.get("pack_version_id", type=int) or 0)
    if pack_version is None:
        errors["pack_version_id"] = "Choose the company this assignment uses."

    section = None
    if (form.get("section_choice") or "existing") == "new":
        name = (form.get("section_name") or "").strip()
        if not name:
            errors["section_name"] = "Give the section a name."
        else:
            section = create_section(db.session, name=name,
                                     term=(form.get("section_term") or "").strip(),
                                     actor=current_user)
    else:
        section = db.session.get(Section, form.get("section_id", type=int) or 0)
        if section is None:
            errors["section_id"] = "Choose the section this assignment is for."

    due_at = _parse_when(form.get("due_at"))
    late_until = _parse_when(form.get("late_until"))
    late_policy = form.get("late_policy") or LATE_CLOSED
    if late_policy == LATE_ACCEPT and (late_until is None or due_at is None
                                       or late_until <= due_at):
        errors["late_until"] = "Late work needs a cut-off after the due date."

    if errors:
        db.session.rollback()
        return render_template(
            "staff/assignment_new.html",
            catalogue=catalogue,
            sections=db.session.scalars(
                db.select(Section).where(Section.archived_at.is_(None)).order_by(Section.name)
            ).all(),
            values=form,
            errors=errors,
        ), 422

    assignment = create_assignment(
        db.session,
        section=section,
        title=title,
        pack_version=pack_version,
        mode=form.get("mode") or "screen",
        due_at=due_at,
        opens_at=_parse_when(form.get("opens_at")),
        late_policy=late_policy,
        late_until=late_until,
        variant_policy=form.get("variant_policy") or "round_robin",
        actor=current_user,
    )
    db.session.commit()
    flash(f"{assignment.title} is ready. Students join with {section.join_code}.")
    return redirect(url_for("staff.index"))


@bp.post("/assignments/<assignment>/clone")
@staff_view
def assignment_clone(assignment: str):
    from datetime import timedelta

    found = _assignment_or_404(assignment)
    days = request.form.get("shift_days", type=int)
    if days is None:
        flash("Say how many days to move the dates by.")
        return redirect(url_for("staff.index"))

    clone = clone_assignment(db.session, found, shift=timedelta(days=days), actor=current_user)
    db.session.commit()
    flash(f"{clone.title} cloned with dates moved by {days} days.")
    return redirect(url_for("staff.index"))


@bp.get("/sections/<int:section_id>/availability")
@staff_view
def section_availability(section_id: int):
    section = db.session.get(Section, section_id)
    if section is None:
        abort(404)
    available = multicompany.available_content_pack_ids(db.session, section_id)
    packs = db.session.execute(
        db.select(ContentPack).order_by(ContentPack.company_name)
    ).scalars()
    rows = [
        {"id": cp.id, "name": cp.company_name, "available": cp.id in available}
        for cp in packs
    ]
    return render_template("staff/availability.html", section=section, packs=rows)


@bp.post("/sections/<int:section_id>/availability")
@staff_view
def section_availability_set(section_id: int):
    section = db.session.get(Section, section_id)
    if section is None:
        abort(404)
    content_pack_id = request.form.get("content_pack_id", type=int)
    available = request.form.get("available") == "1"
    if content_pack_id:
        multicompany.set_availability(
            db.session, section_id=section_id, content_pack_id=content_pack_id,
            available=available, actor=current_user,
        )
        db.session.commit()
        flash("Availability updated. Books already open are not affected.")
    return redirect(url_for("staff.section_availability", section_id=section_id))


@bp.post("/sections/<int:section_id>/join-code")
@staff_view
def section_rotate_code(section_id: int):
    section = db.session.get(Section, section_id)
    if section is None:
        abort(404)
    rotate_join_code(db.session, section, actor=current_user)
    db.session.commit()
    flash(f"{section.name} now joins with {section.join_code}.")
    return redirect(url_for("staff.index"))


# ── Catalogue (I1.7, I1.10) ──────────────────────────────────────────────────────────────
# The catalogue lists what the app holds and takes a pack the generator made. It does not author
# anything: a company is a chart of accounts, a narrative, a document set and an answer key, and
# the workbook is the tool for building one.

MAX_PACK_BYTES = 60 * 1024 * 1024


def _catalogue_rows():
    rows = db.session.execute(
        db.select(ContentPack, PackVersion)
        .join(PackVersion, PackVersion.content_pack_id == ContentPack.id)
        .order_by(ContentPack.company_name, PackVersion.version.desc())
    ).all()
    used = dict(
        db.session.execute(
            db.select(Workspace.pack_version_id, db.func.count())
            .where(Workspace.archived_at.is_(None))
            .group_by(Workspace.pack_version_id)
        ).all()
    )
    catalogue: dict[str, dict] = {}
    for pack, version in rows:
        entry = catalogue.setdefault(pack.slug, {"company_name": pack.company_name,
                                                 "slug": pack.slug, "versions": []})
        entry["versions"].append({
            "version": version.version,
            "period": f"{version.period_start:%-d %b %Y} – {version.period_end:%-d %b %Y}",
            "scope_tags": version.scope_tags or [],
            "has_images": version.has_images,
            "in_use": used.get(version.id, 0),
            "uploaded_at": version.uploaded_at,
        })
    return list(catalogue.values())


@bp.get("/catalogue")
@staff_view
def catalogue():
    return render_template("staff/catalogue.html", companies=_catalogue_rows(), problems=[])


@bp.post("/catalogue")
@staff_view
def catalogue_upload():
    upload = request.files.get("pack")
    if upload is None or not upload.filename:
        flash("Choose a pack zip to upload.")
        return redirect(url_for("staff.catalogue"))

    try:
        version = import_pack_zip(db.session, upload.stream, actor=current_user)
    except PackImportRefused as refused:
        db.session.rollback()
        return render_template(
            "staff/catalogue.html", companies=_catalogue_rows(), problems=refused.problems
        ), 422

    db.session.commit()
    pack = db.session.get(ContentPack, version.content_pack_id)
    flash(f"{pack.company_name} version {version.version} is in the catalogue.")
    return redirect(url_for("staff.catalogue"))
