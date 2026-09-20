"""Route decorators. ``workspace_view`` (T3.3) is on every ``/w/`` route; a guard test walks the
URL map to confirm it.
"""

from __future__ import annotations

from functools import wraps

from flask import abort, g, render_template
from flask_login import current_user, login_required

from . import messages
from .extensions import db
from .models import (
    ROLE_GRADER,
    ROLE_INSTRUCTOR,
    ContentPack,
    PackVersion,
    User,
    Variant,
    Workspace,
)
from .presentation import build_company

STAFF_ROLES = frozenset({ROLE_GRADER, ROLE_INSTRUCTOR})


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
        is_staff = current_user.role in STAFF_ROLES
        if not (is_owner or is_staff):
            abort(404)
        if ws.archived_at is not None and not is_staff:
            abort(404)

        pv = db.session.get(PackVersion, ws.pack_version_id)
        cp = db.session.get(ContentPack, pv.content_pack_id)
        company = build_company(pv, cp)

        g.workspace = ws
        g.pack_version = pv
        # Which version of the company this is. Companies ship in versions with
        # different figures, and until now nothing on screen said which you had.
        g.variant_code = (
            db.session.get(Variant, ws.variant_id).code if ws.variant_id else None
        )
        g.company = company
        g.read_only = is_staff or ws.archived_at is not None or ws.status == "submitted"
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
