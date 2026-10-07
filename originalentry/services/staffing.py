"""Adding and re-roling staff from inside the app.

Until now a teacher account existed only if somebody ran ``flask staff add`` on the production
dyno, which wrote no audit record and sent no email.
"""

from __future__ import annotations

from flask import current_app
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import email as auth_email
from ..auth import tokens
from ..models import ROLE_STUDENT, User
from . import staff_actions


class StaffingRefused(Exception):
    """Said to an administrator, so it names the conflict and what to do instead."""


def _by_email(session: Session, email: str) -> User | None:
    """Case-insensitively, because uq_user_lower_email is: a lookup that is not would create a
    duplicate the index then refuses, turning a polite refusal into an IntegrityError."""
    return session.scalars(
        select(User).where(func.lower(User.email) == email.strip().lower())).first()


def _link(raw_token: str) -> str:
    base = current_app.extensions["originalentry_config"].APP_BASE_URL.rstrip("/")
    return f"{base}/auth/verify/{raw_token}"


def invite(session: Session, *, email: str, role: str, given: str, family: str, actor) -> User:
    existing = _by_email(session, email)
    if existing is not None and existing.role == ROLE_STUDENT:
        raise StaffingRefused(
            f"{existing.email} already has a student account. A teacher who is also a student "
            f"here needs a separate staff address, so that one person's marks and another's "
            f"marking never share a sign-in.")
    if existing is not None:
        raise StaffingRefused(
            f"{existing.email} already has a staff account. Change their role instead.")

    user = User(email=email.strip(), role=role, given_name=given, family_name=family)
    session.add(user)
    session.flush()

    # ip=None on purpose: the per-IP ceiling is thirty an hour and would throttle an admin adding
    # a department from one desk. The per-address limits, which protect the recipient, still
    # apply -- the guard in _enforce_rate_limits is `if ip_hash:`.
    raw_token, code = tokens.issue_token(session, user.email, user_id=user.id, ip=None)
    auth_email.send_sign_in_email(user.email, _link(raw_token), code)
    staff_actions.record(session, actor, staff_actions.STAFF_INVITED, "user", user.id,
                         detail={"role": role})
    return user
