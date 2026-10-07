"""``admin_view``: the guard on routes only an administrator may reach.

404 rather than 403, for the reason ``staff_view`` already gives: a refusal that confirms the page
exists is a refusal that tells a prober something.
"""

from __future__ import annotations

from functools import wraps

from flask import abort
from flask_login import current_user, login_required

from .decorators import ADMIN_ROLES


def admin_view(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if current_user.role not in ADMIN_ROLES:
            abort(404)
        return view(*args, **kwargs)

    wrapped._is_admin_view = True
    # An admin is staff: ADMIN_ROLES is a subset of STAFF_ROLES, so an admin-only route requires
    # staff a fortiori. tests/guards/test_structure.py asks whether every console route requires
    # staff, not which decorator spelled it, and would otherwise read an admin route as unguarded.
    wrapped._is_staff_view = True
    return wrapped
