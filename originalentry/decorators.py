"""Route decorators. ``workspace_view`` (T3.3) is on every ``/w/`` route; a guard test walks the
URL map to confirm it.
"""

from __future__ import annotations

from functools import wraps

from flask import abort, current_app, g, render_template, request
from flask_login import current_user, login_required

from . import messages
from .extensions import db
from .models import (
    KIND_PROBLEM_SET,
    ROLE_ADMIN,
    ROLE_GRADER,
    ROLE_INSTRUCTOR,
    Assignment,
    ContentPack,
    PackVersion,
    SectionStaff,
    User,
    Variant,
    Workspace,
)
from .presentation import build_company
from .workspaces import is_own_practice

STAFF_ROLES = frozenset({ROLE_GRADER, ROLE_INSTRUCTOR, ROLE_ADMIN})
ADMIN_ROLES = frozenset({ROLE_ADMIN})


def my_section_ids() -> frozenset[int]:
    """The sections this staff member teaches, loaded once per request.

    Cached on ``g`` because workspace_view runs on every /w/ route and a console page checks
    several times: one query per request, not one per check.
    """
    if not hasattr(g, "_my_section_ids"):
        g._my_section_ids = frozenset(db.session.scalars(
            db.select(SectionStaff.section_id).filter_by(user_id=current_user.id)
        ).all())
    return g._my_section_ids


def may_see_section(section_id: int) -> bool:
    """Whether the signed-in staff member may see this section's students.

    One function, because a scoping rule implemented in four places is a scoping rule with four
    chances to differ: a half-disabled guard is worse than either state.

    ``SCOPED_VISIBILITY`` has **two** readers that decide what somebody may see, not one: this
    function, and ``staff.views._scoped``. Every route with an id to ask about asks here; a list
    query has no id, so ``_scoped`` asks these same two questions in the same order for those.
    Two named helpers is the shape that is safe; a flag checked inline at a call site is the shape
    that is not, because that is what leaves half the routes scoped and half not. Change the order
    or the exemption in one and it has to change in the other.

    ``grep SCOPED_VISIBILITY`` finds two more, and neither decides anything: ``app.py`` logs a
    warning at startup when it is off, and ``layouts/staff.html`` shows the banner that says so.
    """
    if not current_app.config["SCOPED_VISIBILITY"]:
        return True
    if current_user.role in ADMIN_ROLES:
        return True
    return section_id in my_section_ids()


#: The routes that belong to a chapter problem set, and to nothing else.
#:
#: This is the fence around the only exemption in the application. A problem set relaxes T8.8 (a
#: signature never reaches the student) and A8 (no answer-key value reaches a student), because a
#: self-grading problem has to show a student what they misunderstood and, behind a button, the
#: answer. An exemption that is not fenced is a hole, so these routes 404 in any workspace whose
#: pack is not a problem set. (A7 is **not** exempted: the screens say "matches", not "correct".)
PROBLEM_SET_ENDPOINTS = frozenset({
    "student.problems",
    "student.problem",
    "student.problem_submit",
    "student.problem_reveal",
})

#: The ``/w/`` routes that mean the same thing for either kind of pack.
#:
#: Everything *not* in either set is practice-set only, which is the safe default: a route added
#: later cannot leak into a problem set by being forgotten. ``tests/guards/test_problem_set_fence``
#: lists the practice-only routes explicitly so the classification stays a decision somebody made.
SHARED_WORKSPACE_ENDPOINTS = frozenset({
    "student.overview",         # the landing page for either kind of work
    "student.how_to",           # how to use the application
    "student.reference_index",  # the reference material
    "student.reference",
    "student.marks",            # marks release applies to both
    "student.submit",           # a student hands a problem set in too
    "student.submit_confirm",
})


def _fence(content_pack) -> None:
    """404 a route that does not belong to this workspace's kind of pack, in both directions.

    Here rather than on each route because ``workspace_view`` is the only way into a ``/w/`` URL,
    and a fence with twenty-nine copies is a fence with twenty-nine chances to forget one.
    """
    endpoint = request.endpoint or ""
    if endpoint in SHARED_WORKSPACE_ENDPOINTS:
        return
    wants_problem_set = endpoint in PROBLEM_SET_ENDPOINTS
    if wants_problem_set != (content_pack.kind == KIND_PROBLEM_SET):
        abort(404)


def workspace_view(view):
    """Load the workspace by public id, enforce ownership, resolve the company slug, and set
    ``g.workspace`` / ``g.company`` / ``g.read_only``. Returns 404 (not 403) for a workspace the
    caller may not see, so a probe cannot confirm it exists (T3.3).

    Archived books (I1.12) stay open to staff and closed to the student: the student has been
    given a fresh set and these are no longer where they work."""

    @wraps(view)
    @login_required
    def wrapped(*, workspace, company_slug, **kwargs):
        ws = db.session.execute(
            db.select(Workspace).filter_by(public_id=workspace)
        ).scalar_one_or_none()
        if ws is None:
            abort(404)

        is_owner = ws.student_id == current_user.id
        # Staff see a student's books only for a section they teach. An admin sees all of them.
        # One scalar to reach the section; may_see_section caches the rest per request.
        is_staff = current_user.role in STAFF_ROLES and may_see_section(
            db.session.scalar(db.select(Assignment.section_id).filter_by(id=ws.assignment_id)))
        if not (is_owner or is_staff):
            abort(404)
        if ws.archived_at is not None and not is_staff:
            abort(404)

        pv = db.session.get(PackVersion, ws.pack_version_id)
        cp = db.session.get(ContentPack, pv.content_pack_id)
        company = build_company(pv, cp)

        # After the ownership checks, so a foreign caller is still refused before the kind of
        # pack is even consulted -- a probe must not be able to tell the two refusals apart.
        _fence(cp)

        g.workspace = ws
        g.pack_version = pv
        g.content_pack = cp
        # Which version of the company this is. Companies ship in versions with
        # different figures, and until now nothing on screen said which you had.
        g.variant_code = (
            db.session.get(Variant, ws.variant_id).code if ws.variant_id else None
        )
        g.company = company
        # Staff are read-only in a student's books -- but not in their own practice copy, which
        # they are working the way a student does. The same definition the write path's
        # ``_check_gates`` consults, because a screen that lets you type and a write path that
        # refuses you is worse than either answer alone. Archived and submitted are untouched: a
        # practice copy that has been handed in reads as a student's does.
        g.read_only = (
            (is_staff and not is_own_practice(ws, current_user))
            or ws.archived_at is not None
            or ws.status == "submitted"
        )
        if is_staff and not is_owner:
            # Staff see whose books these are, on every page of them (I2.4).
            student = db.session.get(User, ws.student_id)
            name = f"{student.given_name} {student.family_name}".strip() or student.email
            g.read_only_message = (
                messages.viewing_archived_books(name, f"{ws.archived_at:%-d %b %Y}")
                if ws.archived_at is not None
                else messages.viewing_students_books(name)
            )
        elif ws.status == "submitted":
            g.read_only_message = messages.READ_ONLY_SUBMITTED
        else:
            g.read_only_message = None

        # The switch menu: the owning student's other live workspaces, so they can move between
        # companies they have open (M3.4). Staff viewing a student do not get it.
        g.switch_targets = _switch_targets(ws) if is_owner and not is_staff else []

        # A slug that is not this workspace's company shows a mismatch page — never a silent
        # redirect (M3.4).
        if company.slug != company_slug:
            return render_template("student/company_mismatch.html"), 200

        return view(**kwargs)

    wrapped._is_workspace_view = True  # let the structure guard confirm every /w/ route uses it
    return wrapped


def workspaces_of(student_id: int, *, excluding: int | None = None) -> list[dict]:
    """A student's live workspaces, named by their company.

    Used twice: the switch menu inside the books (M3.4), which excludes the set you are already
    looking at, and the account menu in the chrome, which lists them all.
    """
    query = (
        db.select(Workspace, ContentPack)
        .join(PackVersion, Workspace.pack_version_id == PackVersion.id)
        .join(ContentPack, PackVersion.content_pack_id == ContentPack.id)
        .where(Workspace.student_id == student_id, Workspace.archived_at.is_(None))
        .order_by(ContentPack.company_name)
    )
    if excluding is not None:
        query = query.where(Workspace.id != excluding)
    return [
        {"public_id": ws.public_id, "name": cp.company_name, "slug": cp.slug}
        for ws, cp in db.session.execute(query).all()
    ]


def _switch_targets(workspace) -> list[dict]:
    """The owning student's *other* live workspaces, for the switch menu (M3.4)."""
    return workspaces_of(workspace.student_id, excluding=workspace.id)
