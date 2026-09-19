"""The public landing page. Served at ``/`` to everyone, signed in or not; a signed-in visitor
gets a link straight to their books, everyone else the sign-in and join calls to action.
"""

from __future__ import annotations

from flask import Blueprint, render_template

bp = Blueprint("public", __name__)


@bp.get("/")
def landing():
    return render_template("public/landing.html")
