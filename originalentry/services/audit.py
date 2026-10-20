"""Writing the durable audit trail (AuditLog).

Kept narrow and side-effect-light: ``should_audit`` is a pure decision the request hook and the
tests share, and ``record`` turns an actor plus a few request facts into one row. The Flask
request globals are read in the hook (app.py), not here, so this module stays testable without an
application context.

Privacy: the IP is hashed the one-way way login_token hashes it (never a raw address), the actor's
email is snapshotted so the row outlives the account, and ``detail`` is expected to carry ids and
route parameters only -- the caller must not pass form bodies or typed credentials.
"""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..auth.tokens import hash_ip
from ..decorators import STAFF_ROLES
from ..models import AuditLog

# A dashboard shows a window, not the whole table: the audit log grows without bound (it is never
# purged), so an unbounded read would eventually be the slowest page in the console.
DEFAULT_LIMIT = 200
MAX_LIMIT = 2000

# Students' routine activity stays in activity_event (PII-light, purged with the workspace). The
# durable trail is for privileged actors and for authentication, which is every request under the
# auth blueprint regardless of who makes it (a failed sign-in has no user yet).
#
# Who counts as staff is decorators.STAFF_ROLES and is imported, never restated: this codebase has
# had that set written out in four places before, and a trail that disagreed with the guard about
# who is staff would under-record exactly the people it exists to record.
AUTH_BLUEPRINT = "auth"
# Endpoints that are never worth a row: the health probe and static files are not "activity".
SKIP_ENDPOINTS = frozenset({"static", "healthz"})


def should_audit(blueprint: str | None, endpoint: str | None, role: str | None,
                 is_authenticated: bool) -> bool:
    """Whether one request belongs in the durable trail.

    True for any request by a signed-in staff/admin user, and for anything under the auth
    blueprint (so a failed or anonymous sign-in attempt is still recorded). False for a student's
    own workspace traffic -- that is activity_event's job, and logging it here would make a
    purgeable, PII-light record durable and identifying, which the retention split forbids.
    """
    if endpoint in SKIP_ENDPOINTS:
        return False
    if blueprint == AUTH_BLUEPRINT:
        return True
    return is_authenticated and role in STAFF_ROLES


def record(session: Session, *, action: str, actor=None, method: str | None = None,
           status: int | None = None, target_type: str | None = None,
           target_id: int | None = None, ip: str | None = None,
           detail: dict | None = None) -> AuditLog:
    """Add one audit row to the session (the caller commits).

    ``actor`` is a User or None; its id, email and role are snapshotted. ``action`` is the endpoint
    name, which reads as what was done ("staff.answer_key_print", "auth.sign_in").
    """
    event = AuditLog(
        action=action,
        method=method,
        status=status,
        target_type=target_type,
        target_id=target_id,
        actor_id=getattr(actor, "id", None),
        actor_label=getattr(actor, "email", None),
        actor_role=getattr(actor, "role", None),
        ip_hash=hash_ip(ip),
        detail=detail or {},
    )
    session.add(event)
    return event


def recent(session: Session, *, q: str | None = None,
           limit: int = DEFAULT_LIMIT) -> list[AuditLog]:
    """The most recent audit rows, newest first, optionally filtered by a substring that matches
    either the actor's label or the action. ``limit`` is clamped so a hand-edited URL cannot ask
    for the whole table."""
    limit = max(1, min(limit, MAX_LIMIT))
    stmt = select(AuditLog).order_by(AuditLog.at.desc()).limit(limit)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(AuditLog.actor_label.ilike(like), AuditLog.action.ilike(like)))
    return list(session.scalars(stmt).all())
