"""Route decorators. ``workspace_view`` (T3.3) is on every ``/w/`` route; a guard test walks the
URL map to confirm it.
"""

from __future__ import annotations

from functools import wraps

from flask import abort, g, render_template
from flask_login import current_user, login_required

from . import messages
from .extensions import db
from .models import ROLE_GRADER, ROLE_INSTRUCTOR, ContentPack, PackVersion, Workspace
from .presentation import build_company

STAFF_ROLES = frozenset({ROLE_GRADER, ROLE_INSTRUCTOR})


def workspace_view(view):
    """Load the workspace by public id (excluding archived), enforce ownership, resolve the
    company slug, and set ``g.workspace`` / ``g.company`` / ``g.read_only``. Returns 404 (not
    403) for a workspace the caller may not see, so a probe cannot confirm it exists (T3.3)."""

    @wraps(view)
    @login_required
    def wrapped(*, workspace, company_slug, **kwargs):
        ws = db.session.execute(
            db.select(Workspace).filter_by(public_id=workspace, archived_at=None)
        ).scalar_one_or_none()
        if ws is None:
            abort(404)

        is_owner = ws.student_id == current_user.id
        is_staff = current_user.role in STAFF_ROLES
        if not (is_owner or is_staff):
            abort(404)

        pv = db.session.get(PackVersion, ws.pack_version_id)
        cp = db.session.get(ContentPack, pv.content_pack_id)
        company = build_company(pv, cp)

        g.workspace = ws
        g.pack_version = pv
        g.company = company
        g.read_only = is_staff or ws.status == "submitted"
        g.read_only_message = messages.READ_ONLY_SUBMITTED if ws.status == "submitted" else None

        # A slug that is not this workspace's company shows a mismatch page — never a silent
        # redirect (M3.4).
        if company.slug != company_slug:
            return render_template("student/company_mismatch.html"), 200

        return view(**kwargs)

    wrapped._is_workspace_view = True  # let the structure guard confirm every /w/ route uses it
    return wrapped
