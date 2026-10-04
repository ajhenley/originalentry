"""Sign-in, sign-out and joining by email (T9, E1–E4).

The flow is an emailed magic link **plus** a six-digit code. A GET on the link only shows a
confirmation page — institutional mail scanners open links before the person does, so GET must
consume nothing; the POST behind the button is what starts the session. The code covers a scanner
that goes further, and reading mail on a phone while working on a laptop.

Sign-in gives the **same response whether or not the address has an account** (E1), so the page
never reveals who is enrolled. A new student joins with a class code, a name and an email; the
account is created only when they verify the link — nobody is enrolled at an address they cannot
receive mail at (E4).
"""

from __future__ import annotations

from datetime import UTC, datetime

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import login_user, logout_user
from sqlalchemy import func, select

from ..extensions import db
from ..models import (
    PURPOSE_JOIN,
    ROLE_GRADER,
    ROLE_INSTRUCTOR,
    Enrollment,
    LoginToken,
    Section,
    User,
)
from ..services.assignments import join_with_code
from . import email as email_module
from . import tokens

bp = Blueprint("auth", __name__, url_prefix="/auth")

STAFF_ROLES = {ROLE_GRADER, ROLE_INSTRUCTOR}
_APP_BASE = "APP_BASE_URL"


def _client_ip() -> str | None:
    return request.remote_addr  # ProxyFix trusts one hop, so this is the real client IP


def _link_url(raw_token: str) -> str:
    return url_for("auth.verify_confirm", token=raw_token, _external=True)


def _home_for(user: User) -> str:
    if user.role in STAFF_ROLES:
        return url_for("staff.home") if _has_endpoint("staff.home") else url_for("student.home")
    return url_for("student.home")


def _has_endpoint(name: str) -> bool:
    return name in current_app.view_functions


# ── Sign in ──────────────────────────────────────────────────────────────────────────────

@bp.get("/sign-in")
def sign_in_form():
    return render_template("auth/sign_in.html")


@bp.post("/sign-in", endpoint="sign_in")
def sign_in():
    email = (request.form.get("email") or "").strip()
    session["auth_keep"] = request.form.get("keep_signed_in") == "1"
    session["auth_email"] = email

    user = db.session.scalars(
        select(User).where(func.lower(User.email) == email.lower())
    ).one_or_none()

    # Only mint and send for an address that has an account. The response is identical either way,
    # so this never tells an outsider who is enrolled (E1); strangers are not emailed.
    if user is not None and email:
        try:
            raw_token, code = tokens.issue_token(
                db.session, email, user_id=user.id, ip=_client_ip()
            )
            email_module.send_sign_in_email(email, _link_url(raw_token), code)
            db.session.commit()
        except tokens.RateLimited as limited:
            db.session.rollback()
            flash(limited.message)
            return render_template("auth/sign_in.html"), 429
        except email_module.EmailError:
            db.session.rollback()
            flash(
                "We could not send the email just now. Your work is safe. Try again in a minute, "
                "or ask your instructor for a sign-in code."
            )
            return render_template("auth/sign_in.html"), 502

    return render_template("auth/check_email.html", email=email)


# ── Verify a link (GET is scanner-safe; POST consumes) ───────────────────────────────────

@bp.get("/verify/<token>", endpoint="verify_confirm")
def verify_confirm(token):
    if tokens.find_valid_link(db.session, token) is None:
        return render_template("auth/link_expired.html"), 200
    # Consume nothing here — a scanner may have opened this. The button POSTs to consume.
    return render_template("auth/verify.html", token=token)


@bp.post("/verify", endpoint="verify")
def verify():
    token = request.form.get("token", "")
    row = tokens.consume_link(db.session, token)
    if row is None:
        db.session.rollback()
        return render_template("auth/link_expired.html"), 200
    return _complete_sign_in(row)


# ── Verify a code ────────────────────────────────────────────────────────────────────────

@bp.get("/code")
def code_form():
    return render_template("auth/code.html", email=session.get("auth_email", ""))


@bp.post("/code", endpoint="code")
def code():
    email = (request.form.get("email") or session.get("auth_email") or "").strip()
    entered = (request.form.get("code") or "").strip()
    try:
        row = tokens.consume_code(db.session, email, entered)
    except tokens.CodeLocked as locked:
        db.session.rollback()
        flash(locked.message)
        return render_template("auth/code.html", email=email), 429
    if row is None:
        db.session.rollback()
        # A correct code that is simply spent or stale deserves to be told so; anything else gets
        # the generic line, so a guess cannot learn whether a sign-in is pending (E1).
        flash(
            tokens.explain_miss(db.session, email, entered)
            or "That code did not match. Check it and try again."
        )
        return render_template("auth/code.html", email=email), 422
    return _complete_sign_in(row)


# ── Public join (new student, E4) ────────────────────────────────────────────────────────

@bp.get("/join")
def join_form():
    return render_template("auth/join.html")


@bp.post("/join", endpoint="join")
def join():
    code_text = (request.form.get("code") or "").strip().upper()
    given = (request.form.get("given_name") or "").strip()
    family = (request.form.get("family_name") or "").strip()
    email = (request.form.get("email") or "").strip()

    section = db.session.scalars(
        select(Section).where(
            Section.join_code == code_text,
            Section.join_code_active.is_(True),
            Section.archived_at.is_(None),
        )
    ).one_or_none()
    if section is None:
        flash("That join code does not match an open section. Check it with your instructor.")
        return render_template("auth/join.html"), 422
    if not (given and family and email):
        flash("Enter your name and email so we can send your sign-in link.")
        return render_template("auth/join.html"), 422

    session["auth_email"] = email
    session["auth_keep"] = False
    try:
        raw_token, otc = tokens.issue_token(
            db.session, email, purpose=PURPOSE_JOIN, ip=_client_ip(),
            join_section_id=section.id, join_given_name=given, join_family_name=family,
        )
        email_module.send_sign_in_email(email, _link_url(raw_token), otc)
        db.session.commit()
    except tokens.RateLimited as limited:
        db.session.rollback()
        flash(limited.message)
        return render_template("auth/join.html"), 429
    except email_module.EmailError:
        db.session.rollback()
        flash("We could not send the email just now. Try again in a minute.")
        return render_template("auth/join.html"), 502
    return render_template("auth/check_email.html", email=email)


# ── Completion ───────────────────────────────────────────────────────────────────────────

def _complete_sign_in(token: LoginToken):
    user = _user_for(token)
    if user is None:
        db.session.rollback()
        return render_template("auth/link_expired.html"), 200

    user.last_sign_in_at = datetime.now(UTC)
    keep = bool(session.pop("auth_keep", False)) and user.role not in STAFF_ROLES
    session.pop("auth_email", None)
    session.permanent = keep  # keep-signed-in → the 14-day remember cookie; else a browser session
    tokens.purge_expired(db.session)  # opportunistic (OPS-7)
    db.session.commit()

    login_user(user, remember=keep)
    return redirect(_home_for(user))


def _user_for(token: LoginToken) -> User | None:
    if token.purpose == PURPOSE_JOIN:
        return _join_user(token)
    if token.user_id is not None:
        return db.session.get(User, token.user_id)
    return db.session.scalars(
        select(User).where(func.lower(User.email) == token.email.lower())
    ).one_or_none()


def _join_user(token: LoginToken) -> User | None:
    if token.join_section_id is None:
        return None
    user = db.session.scalars(
        select(User).where(func.lower(User.email) == token.email.lower())
    ).one_or_none()
    if user is None:
        user = User(
            email=token.email,
            given_name=token.join_given_name or "",
            family_name=token.join_family_name or "",
        )
        db.session.add(user)
        db.session.flush()
    section = db.session.get(Section, token.join_section_id)
    if section is None:
        return None
    # Reuse the enrolment path so their books open for every assignment already open (I1.4).
    already = db.session.scalars(
        select(Enrollment).where(
            Enrollment.section_id == section.id, Enrollment.user_id == user.id
        )
    ).one_or_none()
    if already is None:
        join_with_code(db.session, code=section.join_code, student=user)
    return user


@bp.get("/sign-out")
def sign_out():
    logout_user()
    return redirect(url_for("auth.sign_in_form"))
