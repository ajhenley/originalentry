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
from ..decorators import ADMIN_ROLES
from ..models import ROLE_ADMIN, ROLE_INSTRUCTOR, ROLE_STUDENT, User
from . import staff_actions

# The roles this app offers, as opposed to the roles it understands. ``grader`` is understood --
# accounts hold it -- and never offered, because nothing in the app branches on it. staff.views
# derives its dropdowns from the same decision.
OFFERED_ROLES = frozenset({ROLE_INSTRUCTOR, ROLE_ADMIN})


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
    # OFFERED_ROLES, not STAFF_ROLES: the latter admits grader, which this app never offers
    # because nothing branches on it. An account that already holds it keeps working.
    if role not in OFFERED_ROLES:
        raise StaffingRefused(f"{role!r} is not a role this app offers.")
    existing = _by_email(session, email)
    if existing is not None and existing.role == ROLE_STUDENT:
        raise StaffingRefused(
            f"{existing.email} already has a student account. A teacher who is also a student "
            f"here needs a separate staff address, so that one person's marks and another's "
            f"marking never share a sign-in.")
    if existing is not None and existing.deactivated_at is not None:
        # "Change their role instead" would be the wrong instruction here: changing the role of a
        # switched-off account still would not let them in, and a second account would strand
        # their sections and their record on the first one.
        raise StaffingRefused(
            f"{existing.email} already has a staff account that is switched off. Reactivate them "
            f"rather than making a second account: their sections and their record are still "
            f"attached to the one they have.")
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


def other_active_admins(session: Session, excluding_id: int | None) -> list[int]:
    """The ids of the active administrators other than ``excluding_id``.

    One implementation of one invariant. Both ways of taking an administrator's powers away --
    demoting them on the people screen and deactivating their account -- have to ask the same
    question, and the same rule written twice is two chances for the two to differ.

    Lock the whole admin set, the excluded account included, in id order. Every request that asks
    this then selects the identical rows in the identical order, so a second one blocks here until
    the first commits and then re-reads: two administrators demoting or deactivating each other
    cannot both see the other as "remaining". (Locking only the rows other than the excluded one
    would give each request a disjoint lock set and serialise nothing, which is why the target is
    filtered out in Python below rather than in the WHERE clause.)

    No test in this harness proves the lock. The test client points ``db.session`` at the test's
    own connection, so a request never contends with anything and ``with_for_update()`` is
    indistinguishable from no lock. Changing these lines needs reasoning, not a green suite.

    ``select(func.count(...))`` would be the obvious shape and Postgres rejects it outright under
    ``FOR UPDATE``, so the ids come back and Python counts them.
    """
    admins = session.scalars(
        select(User.id).where(
            User.role.in_(ADMIN_ROLES),
            User.deactivated_at.is_(None),
        ).order_by(User.id).with_for_update()).all()
    return [i for i in admins if i != excluding_id]


def deactivate(session: Session, *, target: User, actor) -> User:
    """Take the access away and leave the record.

    Nothing is deleted -- not the account, not their ``section_staff`` rows. A DELETE on
    offboarding is how *"who was teaching ACCT1010 last spring?"* becomes unanswerable.
    """
    # The last-admin rule first, then the self rule. For the sole administrator switching
    # themselves off both apply, and "you are the last administrator" is the one that names the
    # real problem -- staff.people_role orders its two the same way, for the same reason. It is
    # also the only shape in which a route can reach this rule: admin_view means the actor is an
    # administrator, so any other target leaves the actor behind as a remaining one.
    if target.role in ADMIN_ROLES and not other_active_admins(session, target.id):
        raise StaffingRefused(
            "That is the last active administrator. Make someone else an administrator first.")
    if target.id == getattr(actor, "id", None):
        raise StaffingRefused("You cannot deactivate your own account.")

    if target.deactivated_at is not None:
        return target  # already off: no second stamp, and no second audit row saying so
    target.deactivated_at = func.now()
    # Every device, now. The user loader would refuse them anyway, but the bump is what stops a
    # later reactivation from reviving the cookie they were holding when they were switched off.
    target.session_epoch = (target.session_epoch or 0) + 1
    session.flush()
    staff_actions.record(session, actor, staff_actions.STAFF_DEACTIVATED, "user", target.id)
    return target


def reactivate(session: Session, *, target: User, actor) -> User:
    """Clear the stamp. Their sections are still attached, because they were never detached."""
    if target.deactivated_at is None:
        # Already active. An audit trail that records things nobody did is one you cannot read.
        return target
    target.deactivated_at = None
    session.flush()
    staff_actions.record(session, actor, staff_actions.STAFF_REACTIVATED, "user", target.id)
    return target
