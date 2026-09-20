"""``staff_view``: the guard on every ``/staff/`` route (T3.2, T11).

A student who guesses a console URL gets 404, not 403, for the same reason a workspace does: a
refusal that confirms the page exists is a refusal that tells them something.
"""

from __future__ import annotations

from functools import wraps

from flask import abort
from flask_login import current_user, login_required

from .decorators import STAFF_ROLES


def staff_view(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if current_user.role not in STAFF_ROLES:
            abort(404)
        return view(*args, **kwargs)

    wrapped._is_staff_view = True
    return wrapped
