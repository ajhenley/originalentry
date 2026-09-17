"""Sign-in and sign-out.

The real flow (T9) is an emailed magic link plus a six-digit code, with rate limits and hashed
tokens. Until that lands, a **development-only** sign-in logs in an existing user by email so the
student screens work end to end. It refuses to run when ``APP_ENV=production``.
"""

from __future__ import annotations

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import login_user, logout_user
from sqlalchemy import func

from ..extensions import db
from ..models import User

bp = Blueprint("auth", __name__, url_prefix="/auth")


@bp.get("/sign-in")
def sign_in_form():
    return render_template("auth/sign_in.html")


@bp.post("/sign-in", endpoint="sign_in")
def sign_in():
    cfg = current_app.extensions["parchment_config"]
    email = (request.form.get("email") or "").strip()
    keep = request.form.get("keep_signed_in") == "1"

    if cfg.IS_PRODUCTION:
        # The magic-link flow is not built yet; never fake a login in production.
        flash("Sign-in by email is not available yet. Ask your instructor for a code.")
        return render_template("auth/sign_in.html"), 200

    user = db.session.execute(
        db.select(User).where(func.lower(User.email) == email.lower())
    ).scalar_one_or_none()
    if user is None:
        # Same response whether or not the address exists (E1) — no account enumeration.
        flash("If that address has an account, you are now signed in. Otherwise, ask for a code.")
        return render_template("auth/sign_in.html"), 200

    login_user(user, remember=keep)
    return redirect(url_for("student.home"))


@bp.get("/sign-out")
def sign_out():
    logout_user()
    return redirect(url_for("auth.sign_in_form"))
