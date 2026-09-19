"""The public face: the landing page, the privacy policy and the terms.

All three are readable without signing in. Someone deciding whether to hand over their name and
their coursework should not have to hand it over first.
"""

from __future__ import annotations

from flask import Blueprint, render_template

bp = Blueprint("public", __name__)


@bp.get("/")
def landing():
    return render_template("public/landing.html")


@bp.get("/privacy")
def privacy():
    return render_template("public/privacy.html")


@bp.get("/terms")
def terms():
    return render_template("public/terms.html")
