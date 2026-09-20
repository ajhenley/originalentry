"""The public face: the landing page, How it works, the privacy policy and the terms.

All four are readable without signing in. Someone deciding whether to hand over their name and
their coursework should not have to hand it over first — and someone deciding whether to teach
with this should be able to read what it does before making an account.
"""

from __future__ import annotations

from flask import Blueprint, render_template

bp = Blueprint("public", __name__)


@bp.get("/")
def landing():
    return render_template("public/landing.html")


@bp.get("/how-it-works")
def how_it_works():
    """What this software does and why, for someone who has never seen it."""
    return render_template("public/how_it_works.html")


@bp.get("/privacy")
def privacy():
    return render_template("public/privacy.html")


@bp.get("/terms")
def terms():
    return render_template("public/terms.html")
