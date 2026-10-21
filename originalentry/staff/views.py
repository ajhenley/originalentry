"""Console screens (I2). Assignments and Progress so far.

Every screen answers a question of one shape: *which students misunderstand what, and where is
each of them now?* Nothing here writes to a student's books.
"""

from __future__ import annotations

import csv
import io
import json

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
from werkzeug.datastructures import MultiDict

from ..auth import email as auth_email
from ..auth import tokens
from ..decorators import ADMIN_ROLES, STAFF_ROLES, may_see_section, my_section_ids
from ..decorators_admin import admin_view
from ..decorators_staff import staff_view
from ..extensions import db
from ..models import (
    KIND_PROBLEM_SET,
    ROLE_ADMIN,
    ROLE_GRADER,
    ROLE_INSTRUCTOR,
    ROLE_STUDENT,
    AnswerKey,
    Assignment,
    ContentPack,
    Enrollment,
    PackVersion,
    Section,
    SectionStaff,
    User,
    Variant,
    Workspace,
)
from ..models.work import LATE_ACCEPT, LATE_CLOSED
from ..packs import schema
from ..packs.importing import PackImportRefused, import_pack_zip
from ..packs.validate import warn_pack
from ..services import audit, multicompany, staff_actions
from ..services.accommodations import clear_accommodation, set_accommodation
from ..services.assignments import (
    archive_and_restart,
    clone_assignment,
    create_assignment,
    create_section,
    rotate_join_code,
)
from ..services.checkpoint_rules import STAGES, set_checkpoint_rule
from ..services.diagnostics import cohort_csv, cohort_diagnostics
from ..services.grades import (
    final_marks,
    grade_section,
    latest_run,
    release_marks,
    set_comment,
    set_override,
    ungraded_count,
)
from ..services.marks_export import CANVAS, GENERIC, marks_csv
from ..services.mastery import SUPPORT_THRESHOLD, assignment_mastery, concept_detail
from ..services.progress import assignment_progress
from ..services.roster import RosterRefused, import_roster
from ..services.staffing import (
    StaffingRefused,
    deactivate,
    invite,
    other_active_admins,
    reactivate,
)
from ..services.submit import ReopenRefused, reopen_workspace
from ..services.variants import VariantRefused, assign_variant, variants_for
from .key_record import printable_key

BATCH = 10  # workspaces graded per request, so nothing comes near the request limit (I3.7)

bp = Blueprint("staff", __name__, url_prefix="/staff")


def _scoped() -> bool:
    """Whether this viewer's lists are narrowed to the sections they teach.

    The second of the two readers of ``SCOPED_VISIBILITY``; ``decorators.may_see_section`` is the
    other, and owns the rule. A list has no id to ask about, so this asks that function's same two
    questions in the same order and nothing else. Either entry point should lead you to the other:
    change the order or the exemption in one and it has to change in both.
    """
    return (current_app.config["SCOPED_VISIBILITY"]
            and current_user.role not in ADMIN_ROLES)


def _section_or_404(section_id: int) -> Section:
    section = db.session.get(Section, section_id)
    if section is None or not may_see_section(section.id):
        abort(404)
    return section


def _assignment_or_404(public_id: str) -> Assignment:
    assignment = db.session.execute(
        db.select(Assignment).filter_by(public_id=public_id, archived_at=None)
    ).scalar_one_or_none()
    # 404 and not 403, as everywhere else here: a refusal that confirms the assignment exists
    # tells a teacher about a colleague's section.
    if assignment is None or not may_see_section(assignment.section_id):
        abort(404)
    return assignment


def _admin_stats() -> dict[str, int]:
    """The counts at the top of an administrator's console.

    These are deliberately global, which is why ``index`` computes them only for an admin: a
    teacher shown how many students exist in total is being shown across the sections they do not
    teach, and not showing them that is the whole point of ``section_staff``. It is also why no
    teacher pays for these eight queries.

    Two definitions worth stating, because a count that means the wrong thing still looks right:
    students are counted by *enrolment* and de-duplicated, since enrolments are not people and
    one student taking two courses is one student; and ``teachers`` excludes the deactivated,
    who are counted on their own, because a switched-off account has stopped teaching without
    having ceased to exist.
    """
    def count(column, *where) -> int:
        return db.session.scalar(db.select(db.func.count(column)).where(*where)) or 0

    is_staff = User.role.in_(STAFF_ROLES)
    return {
        "teachers": count(User.id, is_staff, User.deactivated_at.is_(None)),
        "deactivated": count(User.id, is_staff, User.deactivated_at.is_not(None)),
        "students": count(db.distinct(Enrollment.user_id)),
        "sections": count(Section.id),
        "assignments": count(Assignment.id, Assignment.archived_at.is_(None)),
        "packs": count(ContentPack.id),
        "versions": count(PackVersion.id),
        "workspaces": count(Workspace.id, Workspace.archived_at.is_(None)),
    }


@bp.get("/")
@staff_view
def index():
    query = (
        db.select(Assignment, Section, ContentPack)
        .join(Section, Assignment.section_id == Section.id)
        .outerjoin(PackVersion, Assignment.fixed_pack_version_id == PackVersion.id)
        .outerjoin(ContentPack, PackVersion.content_pack_id == ContentPack.id)
        .where(Assignment.archived_at.is_(None))
        .order_by(Section.name, Assignment.title)
    )
    if _scoped():
        query = query.join(
            SectionStaff, SectionStaff.section_id == Assignment.section_id
        ).where(SectionStaff.user_id == current_user.id)
    rows = db.session.execute(query).all()

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
    # An empty dashboard and no explanation reads as an outage. It is one sentence, and only when
    # the reason really is that nobody has attached this person to a section yet.
    return render_template("staff/assignments.html", assignments=assignments,
                           stats=_admin_stats() if current_user.role in ADMIN_ROLES else None,
                           teaches_nothing=_scoped() and not my_section_ids())


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
        is_problem_set=_is_problem_set(pack_version),
        variant_codes=variants_for(db.session, found.fixed_pack_version_id)
        if found.fixed_pack_version_id else [],
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


def _archived_rows(assignment: Assignment) -> list[dict]:
    """Books that were archived and replaced (I1.12), with a way back into them.

    Archiving promises the old books stay viewable. That promise needs a link, or an instructor
    answering "what was in there?" a week later has nowhere to click."""
    rows = db.session.execute(
        db.select(Workspace, User, ContentPack)
        .join(User, Workspace.student_id == User.id)
        .join(PackVersion, Workspace.pack_version_id == PackVersion.id)
        .join(ContentPack, PackVersion.content_pack_id == ContentPack.id)
        .where(Workspace.assignment_id == assignment.id, Workspace.archived_at.is_not(None))
        .order_by(Workspace.archived_at.desc())
    ).all()
    return [
        {
            "public_id": workspace.public_id,
            "company_slug": pack.slug,
            "archived_at": workspace.archived_at,
            "student_name": f"{student.given_name} {student.family_name}".strip()
            or student.email,
        }
        for workspace, student, pack in rows
    ]


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
        archived=_archived_rows(found),
        assignment=found,
        section=db.session.get(Section, found.section_id),
        rows=rows,
        only_review=only_review,
        released=found.marks_released_at is not None,
    )


@bp.post("/grading/<assignment>/run")
@staff_view
def grading_run(assignment: str):
    """Grade the next batch (T8.6).

    An ordinary form post grades a batch and comes back to the list, which is the whole feature
    without JavaScript. When `batch.js` asks, the same work is done and the answer carries the
    counts instead, so the script knows whether to ask again. Each batch is committed before the
    answer is sent, so a closed tab loses nothing."""
    found = _assignment_or_404(assignment)
    after = request.form.get("after", type=int)
    graded, total, cursor = grade_section(db.session, found, actor=current_user,
                                          limit=BATCH, after_id=after)
    staff_actions.record(db.session, current_user, staff_actions.GRADE_RUN, "assignment",
                         found.id, detail={"graded": len(graded), "of": total})
    db.session.commit()

    if request.headers.get("X-Batch") == "1":
        return Response(status=200, headers={
            "X-Graded": str(len(graded)),
            "X-Total": str(total),
            "X-Remaining": str(ungraded_count(db.session, found)),
            "X-After": "" if cursor is None else str(cursor),
        })

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
        # Which key these marks came from, so a regrade starts from the same figures.
        variant_code=(db.session.get(Variant, ws.variant_id).code if ws.variant_id else None),
        marks=final_marks(db.session, ws),
        run=run,
        result=run.result if run else None,
    )


@bp.post("/grading/<assignment>/<workspace>/archive")
@staff_view
def workspace_archive(assignment: str, workspace: str):
    found = _assignment_or_404(assignment)
    ws = _workspace_or_404(found, workspace)
    reason = (request.form.get("reason") or "").strip()
    if not reason:
        flash("Say why you are archiving this workspace.")
        return redirect(url_for("staff.grading_detail", assignment=assignment, workspace=workspace))
    archive_and_restart(db.session, ws, reason=reason, actor=current_user)
    db.session.commit()
    flash("Workspace archived. A fresh one is open; the old one stays viewable.")
    return redirect(url_for("staff.grading", assignment=assignment))


@bp.post("/grading/<assignment>/<workspace>/reopen")
@staff_view
def workspace_reopen(assignment: str, workspace: str):
    """Give a handed-in workspace back to the student (S6.5)."""
    found = _assignment_or_404(assignment)
    ws = _workspace_or_404(found, workspace)
    back = redirect(url_for("staff.grading_detail", assignment=found.public_id,
                            workspace=ws.public_id))
    reason = (request.form.get("reason") or "").strip()
    if not reason:
        flash("Say why you are giving this work back.")
        return back

    try:
        reopen_workspace(db.session, ws, reason=reason,
                         until=_parse_when(request.form.get("until")), actor=current_user)
    except (ReopenRefused, ValueError) as refused:
        db.session.rollback()
        flash(str(refused))
        return back

    db.session.commit()
    flash("Given back. They can work on it again; that they handed it in is still on the record.")
    return back


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
    # Computed once and handed to both: the mastery blocks and the sections below describe the
    # same cohort, so they must read it once rather than twice.
    cohort = cohort_diagnostics(db.session, found)
    return render_template(
        "staff/diagnostics.html",
        assignment=found,
        section=db.session.get(Section, found.section_id),
        diagnostics=cohort,
        mastery=assignment_mastery(db.session, found, diagnostics=cohort),
        support_threshold=SUPPORT_THRESHOLD,
        is_problem_set=_is_problem_set(
            db.session.get(PackVersion, found.fixed_pack_version_id)
            if found.fixed_pack_version_id else None),
    )


@bp.get("/diagnostics/<assignment>/concept/<concept_key>")
@staff_view
def concept(assignment: str, concept_key: str):
    """Who is behind one concept. Scoped by its parent, like every console screen with an id."""
    found = _assignment_or_404(assignment)
    try:
        detail = concept_detail(db.session, found, concept_key)
    except LookupError:
        # 404 and not 403 for a concept that does not exist or has been retired, the same way the
        # rest of the console refuses: a different answer would say which keys are real.
        abort(404)
    return render_template(
        "staff/concept.html",
        assignment=found,
        section=db.session.get(Section, found.section_id),
        detail=detail,
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
         "company_name": pack.company_name, "has_images": version.has_images,
         # A chapter problem set is picked and configured differently: the form needs to know
         # which rows are chapters, and how many problems each has, so an instructor sees the
         # ceiling before `problems_required` is refused rather than after.
         "kind": pack.kind,
         "is_problem_set": pack.kind == KIND_PROBLEM_SET,
         "chapter_label": pack.chapter_label,
         "textbook": pack.textbook,
         "problem_count": len((version.manifest or {}).get("documents", []))
         if pack.kind == KIND_PROBLEM_SET else None}
        for version, pack in rows
    ]


def _problem_count(pack_version) -> int:
    """How many problems a chapter pack holds, which is the ceiling on problems_required."""
    return len((pack_version.manifest or {}).get("documents", []))


def _is_problem_set(pack_version) -> bool:
    if pack_version is None:
        return False
    pack = db.session.get(ContentPack, pack_version.content_pack_id)
    return pack is not None and pack.kind == KIND_PROBLEM_SET


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
    course_tz = ZoneInfo(current_app.extensions["originalentry_config"].COURSE_TZ)
    return naive.replace(tzinfo=course_tz) if naive.tzinfo is None else naive


def _possible_prerequisites():
    """Live assignments this one could wait on (M2.5). Ordered by section, then title, because an
    instructor thinks of them as "November, then December" inside one course.

    Scoped like every other list here. Its labels are a section's name and an assignment's title,
    which is a colleague's business and not this teacher's -- and an assignment cannot sensibly
    wait on one in a section you do not teach anyway.
    """
    query = (
        db.select(Assignment, Section)
        .join(Section, Assignment.section_id == Section.id)
        .where(Assignment.archived_at.is_(None))
        .order_by(Section.name, Assignment.title)
    )
    if _scoped():
        query = query.join(
            SectionStaff, SectionStaff.section_id == Assignment.section_id
        ).where(SectionStaff.user_id == current_user.id)
    rows = db.session.execute(query).all()
    return [
        {"public_id": a.public_id, "label": f"{section.name} · {a.title}"}
        for a, section in rows
    ]


def _my_sections():
    """The sections to offer in the dropdown: yours, or every one of them for an admin."""
    query = db.select(Section).where(Section.archived_at.is_(None))
    if _scoped():
        query = query.join(
            SectionStaff, SectionStaff.section_id == Section.id
        ).where(SectionStaff.user_id == current_user.id)
    return db.session.scalars(query.order_by(Section.name)).all()


def _assignment_or_none(public_id: str | None):
    """The posted prerequisite, if there is one. Scoped for the same reason the posted section id
    is: filtering the dropdown is not a permission check, and an assignment in a section you do
    not teach is not one you may name here. It reads as absent rather than as an error, which is
    what an id you were never offered is."""
    if not (public_id or "").strip():
        return None
    found = db.session.execute(
        db.select(Assignment).filter_by(public_id=public_id.strip(), archived_at=None)
    ).scalar_one_or_none()
    if found is None or not may_see_section(found.section_id):
        return None
    return found


@bp.get("/assignments/new")
@staff_view
def assignment_new():
    return render_template(
        "staff/assignment_new.html",
        catalogue=_catalogue(),
        sections=_my_sections(),
        prerequisites=_possible_prerequisites(),
        values=MultiDict(),
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

    policy = form.get("company_policy") or "fixed"
    pack_version = None
    choice_versions: list = []
    if policy == "choice":
        ids = [int(v) for v in form.getlist("choice_pack_version_ids") if v.isdigit()]
        choice_versions = [pv for pv in (db.session.get(PackVersion, i) for i in ids) if pv]
        if len(choice_versions) < 2:
            errors["pack_version_id"] = "Offer at least two companies for students to choose from."
    else:
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
        # Filtering the dropdown is not a permission check: a crafted POST would otherwise plant
        # an assignment in a colleague's section. A form error at 422 rather than a 404, because
        # this route is reached by submitting a form.
        if section is not None and not may_see_section(section.id):
            errors["section_id"] = "That section is not one you teach."

    due_at = _parse_when(form.get("due_at"))
    late_until = _parse_when(form.get("late_until"))
    late_policy = form.get("late_policy") or LATE_CLOSED
    if late_policy == LATE_ACCEPT and (late_until is None or due_at is None
                                       or late_until <= due_at):
        errors["late_until"] = "Late work needs a cut-off after the due date."

    # How many of a chapter's problems count. Refused here rather than defaulted anywhere: the
    # grading component will mark out of every problem and flag for review if this is missing,
    # which is a safety net for a mistake and not a way to create an assignment.
    problems_required = None
    if policy == "choice" and any(_is_problem_set(pv) for pv in choice_versions):
        # One assignment, one count. A choice between chapters of different lengths would mark
        # two students against different denominators under a single problems_required.
        errors["pack_version_id"] = (
            "A chapter problem set cannot be offered as a choice: one assignment has one "
            "number of problems that count."
        )
    elif _is_problem_set(pack_version):
        total = _problem_count(pack_version)
        raw = (form.get("problems_required") or "").strip()
        problems_required = int(raw) if raw.isdigit() else None
        if problems_required is None or not 1 <= problems_required <= total:
            errors["problems_required"] = (
                f"Say how many of this chapter's {total} problems count, as a whole number from "
                f"1 to {total}."
            )

    if errors:
        db.session.rollback()
        return render_template(
            "staff/assignment_new.html",
            catalogue=catalogue,
            sections=_my_sections(),
            prerequisites=_possible_prerequisites(),
            values=form,
            errors=errors,
        ), 422

    assignment = create_assignment(
        db.session,
        section=section,
        title=title,
        pack_version=pack_version,
        choice_pack_versions=choice_versions or None,
        mode=form.get("mode") or "screen",
        due_at=due_at,
        opens_at=_parse_when(form.get("opens_at")),
        late_policy=late_policy,
        late_until=late_until,
        variant_policy=form.get("variant_policy") or "round_robin",
        prerequisite=_assignment_or_none(form.get("prerequisite")),
        problems_required=problems_required,
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
    section = _section_or_404(section_id)
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
    _section_or_404(section_id)  # for the refusal only; the ids below are all this needs
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


@bp.post("/sections/<int:section_id>/roster")
@staff_view
def section_roster_import(section_id: int):
    """Enrol a section from the registrar's CSV (I1.5).

    Importing an address does not make it anyone's account — sign-in is still a link sent to that
    address — so this enrols people, and the people themselves prove the address is theirs."""
    section = _section_or_404(section_id)
    back = redirect(url_for("staff.section_availability", section_id=section_id))

    upload = request.files.get("roster")
    if upload is None or not upload.filename:
        flash("Choose a CSV file to import.")
        return back

    raw = upload.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        flash("That file is not readable as text. Export it from your spreadsheet as CSV.")
        return back

    try:
        report = import_roster(db.session, section=section, csv_text=text, actor=current_user)
    except RosterRefused as refused:
        db.session.rollback()
        flash(str(refused))
        return back

    db.session.commit()
    said = f"Enrolled {report.enrolled}."
    if report.already:
        said += f" {report.already} were already in this section."
    if report.refused:
        lines = ", ".join(f"line {line} ({why})" for line, why in report.refused[:5])
        more = f" and {len(report.refused) - 5} more" if len(report.refused) > 5 else ""
        said += f" Skipped {lines}{more}. Fix those rows and import the file again."
    flash(said)
    return back


@bp.post("/sections/<int:section_id>/join-code")
@staff_view
def section_rotate_code(section_id: int):
    section = _section_or_404(section_id)
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
    # Which variants have a key, so the catalogue can offer the answer-key print (I5.3).
    keyed: dict[int, list[str]] = {}
    for pack_version_id, code in db.session.execute(
        db.select(AnswerKey.pack_version_id, Variant.code)
        .join(Variant, AnswerKey.variant_id == Variant.id)
        .order_by(Variant.code)
    ).all():
        keyed.setdefault(pack_version_id, []).append(code)

    catalogue: dict[str, dict] = {}
    for pack, version in rows:
        entry = catalogue.setdefault(pack.slug, {"company_name": pack.company_name,
                                                 "slug": pack.slug, "versions": []})
        entry["versions"].append({
            "id": version.id,
            "keyed_variants": keyed.get(version.id, []),
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
    return render_template("staff/catalogue.html", companies=_catalogue_rows(),
                           problems=[], warnings=[])


@bp.get("/catalogue/<int:pack_version_id>/key/<variant_code>")
@staff_view
def answer_key_print(pack_version_id: int, variant_code: str):
    """The answer key for one variant, on one page to print (I5.3).

    Staff-only, which is the whole security story: this page is the answers."""
    version = db.session.get(PackVersion, pack_version_id)
    if version is None:
        abort(404)
    pack = db.session.get(ContentPack, version.content_pack_id)
    key = printable_key(db.session, version, variant_code, pack.company_name)
    if key is None:
        abort(404)
    return render_template("print/answer_key.html", key=key, version=version)


@bp.post("/catalogue")
@admin_view
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
            "staff/catalogue.html", companies=_catalogue_rows(),
            problems=refused.problems, warnings=[]
        ), 422

    db.session.commit()
    pack = db.session.get(ContentPack, version.content_pack_id)
    flash(f"{pack.company_name} version {version.version} is in the catalogue.")
    # W1 is a warning, so the pack is already in. Read it back from what was stored — the
    # manifest is exactly the text students will meet — and show the author what it noticed.
    warnings = list(warn_pack(schema.load_pack(version.manifest)))
    if not warnings:
        return redirect(url_for("staff.catalogue"))
    return render_template(
        "staff/catalogue.html", companies=_catalogue_rows(), problems=[], warnings=warnings
    )


@bp.get("/grading/<assignment>/marks.csv")
@staff_view
def grading_marks_csv(assignment: str):
    """The released marks in a shape a gradebook will import (I5.1)."""
    found = _assignment_or_404(assignment)
    preset = CANVAS if request.args.get("preset") == CANVAS else GENERIC
    filename = f"{found.public_id}-marks-{preset}.csv"
    return Response(
        marks_csv(db.session, found, preset=preset),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@bp.post("/progress/<assignment>/accommodation")
@staff_view
def progress_accommodation(assignment: str):
    """Give one student their own deadline, or withdraw it (I1.11)."""
    found = _assignment_or_404(assignment)
    back = redirect(url_for("staff.progress", assignment=found.public_id))
    workspace = _workspace_or_404(found, request.form.get("workspace", ""))
    student = db.session.get(User, workspace.student_id)
    reason = (request.form.get("reason") or "").strip()

    try:
        if request.form.get("withdraw"):
            clear_accommodation(db.session, assignment=found, student=student,
                                reason=reason or "Withdrawn", actor=current_user)
            flash(f"{student.email} is back on the section's deadline.")
        else:
            when = _parse_when(request.form.get("due_at"))
            if when is None:
                flash("Give the date and time their work should close.")
                return back
            set_accommodation(db.session, assignment=found, student=student, due_at=when,
                              late_until=when, reason=reason, actor=current_user)
            flash(f"{student.email} now works to {when:%-d %b %H:%M}.")
    except ValueError as refused:
        flash(str(refused))
        return back

    db.session.commit()
    return back


@bp.post("/progress/<assignment>/variant")
@staff_view
def progress_variant(assignment: str):
    """Hand a variant to one student, where the policy says by hand (I1.3)."""
    found = _assignment_or_404(assignment)
    back = redirect(url_for("staff.progress", assignment=found.public_id))
    workspace = _workspace_or_404(found, request.form.get("workspace", ""))
    code = (request.form.get("variant") or "").strip()

    try:
        assign_variant(db.session, workspace, code, actor=current_user)
    except VariantRefused as refused:
        db.session.rollback()
        flash(str(refused))
        return back

    db.session.commit()
    flash(f"Variant {code} handed out. They can record now.")
    return back


@bp.post("/assignments/<assignment>/checkpoints")
@staff_view
def assignment_checkpoints(assignment: str):
    """Put a deadline on a checkpoint, and decide what it stands in front of (I1.2, S6.3)."""
    found = _assignment_or_404(assignment)
    back = redirect(url_for("staff.index"))

    ordinal = request.form.get("ordinal", type=int)
    if ordinal is None:
        flash("Say which checkpoint this is about.")
        return back

    gates = (request.form.get("gates_stage") or "").strip() or None
    if gates is not None and gates not in STAGES:
        flash(f"A checkpoint can stand in front of {', '.join(STAGES)}.")
        return back

    set_checkpoint_rule(db.session, assignment=found, ordinal=ordinal,
                        deadline_at=_parse_when(request.form.get("deadline_at")),
                        gates_stage=gates, actor=current_user)
    db.session.commit()
    flash(f"Checkpoint {ordinal} updated.")
    return back


# ── people (Task 5): staff accounts, roles and which sections each teaches ─────────────────────

# Two different jobs, kept apart. ASSIGNABLE_ROLES is who this screen *manages*: grader is in it
# so the accounts that already hold that role still appear and can still be re-roled or switched
# off. OFFERED_ROLES is what it *offers*, and grader is not on it.
#
# Not cosmetic. Nothing in the app branches on grader versus instructor -- the spec says so in
# as many words, and giving grader real limits was declined -- so a screen that offers "grader"
# invites an administrator to pick it for a teaching assistant believing it is the lesser
# permission. It is not: that account reads every mark in every section attached to it. Offering
# a choice that does nothing, on the screen that grants access to student marks, is worse than
# offering no choice.
ASSIGNABLE_ROLES = (ROLE_INSTRUCTOR, ROLE_GRADER, ROLE_ADMIN)
OFFERED_ROLES = ((ROLE_INSTRUCTOR, "Teacher"), (ROLE_ADMIN, "Admin"))
OFFERED_VALUES = frozenset(value for value, _label in OFFERED_ROLES)
# What a stored role is called on screen. A grader displays as Teacher, with the stored role noted
# beside it so an administrator can still see what the database holds.
ROLE_LABELS = {ROLE_INSTRUCTOR: "Teacher", ROLE_GRADER: "Teacher", ROLE_ADMIN: "Admin"}
_STAFF_NOTE = ("The sign-in link lasts fifteen minutes. If it has lapsed, they can still sign "
               "in from the sign-in page with this address.")


@bp.get("/students")
@admin_view
def students():
    """Every student, where they are enrolled, and what they have open.

    Admin only. This is every student in the install on one screen, which is the opposite of what
    section scoping does for a teacher, so it is gated by role rather than by section.

    Read-only. Deactivating students is out of scope by design -- the spec puts them under
    rosters and sections, "a different thing" -- so this screen finds people and shows what is
    true of them, and changes nothing.

    One query for the students, one for their enrolments and one for their open books, rather
    than either per row: a roster is the screen most likely to grow past the size somebody
    imagined when they wrote it.
    """
    term = (request.args.get("q") or "").strip()
    query = db.select(User).where(User.role == ROLE_STUDENT)
    if term:
        # Each field matched on its own rather than a concatenation: "Kelly" should find a family
        # name and "roster-keep" an address, and neither should depend on how a full name is
        # assembled for someone with no given name.
        like = f"%{term.lower()}%"
        query = query.where(db.or_(
            db.func.lower(User.email).like(like),
            db.func.lower(User.given_name).like(like),
            db.func.lower(User.family_name).like(like),
        ))
    found = db.session.scalars(
        query.order_by(User.family_name, User.given_name, User.email)).all()
    ids = [u.id for u in found]

    enrolled: dict[int, list[dict]] = {}
    books: dict[int, dict[str, int]] = {}
    if ids:
        for user_id, section_name, source, number in db.session.execute(
            db.select(Enrollment.user_id, Section.name, Enrollment.source,
                      Enrollment.student_number)
            .join(Section, Section.id == Enrollment.section_id)
            .where(Enrollment.user_id.in_(ids))
            .order_by(Section.name)
        ).all():
            enrolled.setdefault(user_id, []).append(
                {"section": section_name, "source": source, "number": number})
        for student_id, status, count in db.session.execute(
            db.select(Workspace.student_id, Workspace.status, db.func.count())
            .where(Workspace.student_id.in_(ids), Workspace.archived_at.is_(None))
            .group_by(Workspace.student_id, Workspace.status)
        ).all():
            books.setdefault(student_id, {})[status] = count

    return render_template(
        "staff/students.html",
        term=term,
        students=[
            {
                "name": f"{u.given_name} {u.family_name}".strip() or "—",
                "email": u.email,
                "enrolled": enrolled.get(u.id, []),
                "books": sorted(books.get(u.id, {}).items()),
                "last_sign_in_at": u.last_sign_in_at,
            }
            for u in found
        ],
    )


@bp.get("/people")
@admin_view
def people():
    staff = db.session.scalars(
        db.select(User).where(User.role.in_(ASSIGNABLE_ROLES)).order_by(User.email)).all()
    sections = db.session.scalars(db.select(Section).order_by(Section.name)).all()
    attached: dict[int, set[int]] = {}
    # Which sections still have somebody active on them. Read off the same pass as `attached`
    # rather than a second query: deactivating a teacher does not detach them, so a section can
    # be fully attached and still have nobody who can open it.
    staffed_by_active: set[int] = set()
    for section_id, user_id, deactivated_at in db.session.execute(
            db.select(SectionStaff.section_id, SectionStaff.user_id, User.deactivated_at)
            .join(User, User.id == SectionStaff.user_id)).all():
        attached.setdefault(user_id, set()).add(section_id)
        if deactivated_at is None:
            staffed_by_active.add(section_id)
    # Task 2 attached every existing section to every existing staff member so nothing broke on
    # deploy; a section with several teachers is where that still needs pruning.
    teachers_per_section = {
        s.id: sum(1 for ids in attached.values() if s.id in ids) for s in sections}
    return render_template(
        "staff/people.html", staff=staff, sections=sections, attached=attached,
        teachers_per_section=teachers_per_section, roles=OFFERED_ROLES, role_labels=ROLE_LABELS,
        offered_values=OFFERED_VALUES,
        needs_teacher=[s for s in sections if s.id not in staffed_by_active],
        crowded=sum(1 for n in teachers_per_section.values() if n > 1))


@bp.post("/people")
@admin_view
def people_add():
    role = request.form.get("role") or ROLE_INSTRUCTOR
    if role not in OFFERED_VALUES:
        flash("Choose a staff role.")
        return redirect(url_for("staff.people"))
    address = (request.form.get("email") or "").strip()
    if "@" not in address:
        flash("Enter an email address.")
        return redirect(url_for("staff.people"))
    try:
        user = invite(db.session, email=address, role=role,
                      given=(request.form.get("given_name") or "").strip(),
                      family=(request.form.get("family_name") or "").strip(),
                      actor=current_user)
    except StaffingRefused as refused:
        db.session.rollback()
        flash(str(refused))
        return redirect(url_for("staff.people"))
    except tokens.RateLimited as limited:
        db.session.rollback()
        flash(str(limited))
        return redirect(url_for("staff.people"))
    except auth_email.EmailError:
        db.session.rollback()
        flash("The invitation email could not be sent, so no account was made. Try again.")
        return redirect(url_for("staff.people"))
    db.session.commit()
    flash(f"{user.email} added and emailed a sign-in link. {_STAFF_NOTE}")
    return redirect(url_for("staff.people"))


def _person_or_404(public_id: str) -> User:
    target = db.session.execute(
        db.select(User).filter_by(public_id=public_id)).scalar_one_or_none()
    if target is None or target.role not in ASSIGNABLE_ROLES:
        abort(404)
    return target


@bp.post("/people/<public_id>/role")
@admin_view
def people_role(public_id: str):
    target = _person_or_404(public_id)
    back = redirect(url_for("staff.people"))
    new_role = request.form.get("role") or ""
    if new_role not in OFFERED_VALUES:
        flash("Choose a staff role.")
        return back
    if target.role in ADMIN_ROLES and new_role not in ADMIN_ROLES:
        # One implementation of the last-admin rule, shared with services.staffing.deactivate:
        # demotion and deactivation are two ways of taking the same powers away, and the same
        # rule written twice is two chances for the two to differ. The lock it holds, and why no
        # test here can prove it, are documented on the helper.
        if not other_active_admins(db.session, target.id):
            flash("That is the last administrator. Make someone else an administrator first.")
            return back
    if target.id == current_user.id:
        flash("You cannot change your own role.")
        return back
    if new_role != target.role:
        staff_actions.record(db.session, current_user, staff_actions.STAFF_ROLE_CHANGED, "user",
                             target.id, detail={"from": target.role, "to": new_role})
        target.role = new_role
        db.session.commit()
        flash(f"{target.email} is now {new_role}.")
    return back


@bp.post("/people/<public_id>/sections")
@admin_view
def people_sections(public_id: str):
    target = _person_or_404(public_id)
    section = db.session.get(Section, request.form.get("section_id", type=int) or 0)
    if section is None:
        # An empty attach list posts no section_id; that is a missing choice, not a missing page.
        flash("Choose a section.")
        return redirect(url_for("staff.people"))
    row = db.session.get(SectionStaff, (section.id, target.id))
    if request.form.get("attach") and row is None:
        db.session.add(SectionStaff(section_id=section.id, user_id=target.id,
                                    added_by_id=current_user.id))
        staff_actions.record(db.session, current_user, staff_actions.SECTION_STAFF_ADDED,
                             "section", section.id, detail={"user_id": target.id})
        flash(f"{target.email} now teaches {section.name}.")
    elif request.form.get("detach") and row is not None:
        db.session.delete(row)
        staff_actions.record(db.session, current_user, staff_actions.SECTION_STAFF_REMOVED,
                             "section", section.id, detail={"user_id": target.id})
        flash(f"{target.email} no longer teaches {section.name}.")
    db.session.commit()
    return redirect(url_for("staff.people"))


@bp.post("/people/<public_id>/active")
@admin_view
def people_active(public_id: str):
    """Switch a staff account off, or back on.

    Off, not gone: the account and its ``section_staff`` rows stay, because those rows are the
    only answer to who taught a class last term. A section left with nobody active says so on
    this screen, so nobody has to remember which ones they are.
    """
    target = _person_or_404(public_id)
    back = redirect(url_for("staff.people"))
    switching_off = bool(request.form.get("deactivate"))
    switching_on = bool(request.form.get("reactivate"))
    if switching_off == switching_on:
        # Both fields are read, and neither direction is the fallback. Reading only one made the
        # other the default for any POST that did not name it -- so an empty or crafted body
        # silently switched an account back on and wrote an audit row saying an administrator had
        # asked for it. A security control must not default to "off".
        flash("Choose whether to deactivate or reactivate that account.")
        return back
    was_off = target.deactivated_at is not None
    try:
        if switching_off:
            deactivate(db.session, target=target, actor=current_user)
        else:
            reactivate(db.session, target=target, actor=current_user)
    except StaffingRefused as refused:
        db.session.rollback()
        flash(str(refused))
        return back
    db.session.commit()
    if switching_off and was_off:
        flash(f"{target.email} was already switched off. Nothing changed.")
    elif switching_off:
        flash(f"{target.email} is no longer active. Their sections and record are untouched.")
    elif was_off:
        flash(f"{target.email} is active again, and teaches the sections they did before.")
    else:
        flash(f"{target.email} was already active. Nothing changed.")
    return back


# ── Activity log (the durable audit trail) ───────────────────────────────────────────────
# Admin-only, because the rows name people: it is the one console screen that reports on staff as
# well as students, which is a different trust level from marking a class.

def _activity_rows(q: str | None, limit: int):
    return audit.recent(db.session, q=q or None, limit=limit)


@bp.get("/activity")
@admin_view
def activity():
    q = (request.args.get("q") or "").strip()
    rows = _activity_rows(q, audit.DEFAULT_LIMIT)
    return render_template("staff/activity.html", rows=rows, q=q, limit=audit.DEFAULT_LIMIT)


@bp.get("/activity/export.csv")
@admin_view
def activity_export():
    """The same view, as a CSV, up to the service's hard limit. Everything the dashboard shows and
    nothing it hides -- the IP is already stored hashed, so the export cannot leak an address."""
    q = (request.args.get("q") or "").strip()
    rows = _activity_rows(q, audit.MAX_LIMIT)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["at", "actor", "role", "action", "method", "status",
                     "target_type", "target_id", "ip_hash", "detail"])
    for r in rows:
        writer.writerow([
            r.at.isoformat() if r.at else "", r.actor_label or "", r.actor_role or "",
            r.action, r.method or "", r.status if r.status is not None else "",
            r.target_type or "", r.target_id if r.target_id is not None else "",
            r.ip_hash or "", json.dumps(r.detail or {}, sort_keys=True),
        ])
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": 'attachment; filename="activity-log.csv"'},
    )
