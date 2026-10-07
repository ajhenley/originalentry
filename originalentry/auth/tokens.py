"""Sign-in tokens and codes (E2).

Only hashes are stored: the link token as SHA-256, the code and the client IP as HMACs keyed by
``SECRET_KEY``. A link or a code is valid for 15 minutes and can be used once; using either
consumes the row. The code allows five attempts. Rate limits are counted straight from
``login_token`` (created_at), so there is no Redis.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from flask import current_app
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..models import PURPOSE_SIGN_IN, PURPOSE_STAFF_CODE, LoginToken

TOKEN_TTL_MINUTES = 15
STAFF_CODE_TTL_MINUTES = 30
MAX_CODE_ATTEMPTS = 5
PURGE_AFTER_DAYS = 30

# Rate limits (E2), counted from login_token.
EMAILS_PER_ADDRESS_15MIN = 3
EMAILS_PER_ADDRESS_HOUR = 10
EMAILS_PER_IP_HOUR = 30


class AuthError(Exception):
    """A student-safe auth failure. ``message`` is finished text."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class RateLimited(AuthError):
    pass


class CodeLocked(AuthError):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def _secret() -> bytes:
    return current_app.config["SECRET_KEY"].encode()


def _hmac_hex(label: str, value: str) -> str:
    return hmac.new(_secret(), f"{label}:{value}".encode(), hashlib.sha256).hexdigest()


def hash_ip(ip: str | None) -> str | None:
    """HMAC of the client IP — used for rate limits, never stored raw, never displayed."""
    return _hmac_hex("ip", ip) if ip else None


def _hash_code(code: str) -> str:
    return _hmac_hex("code", code)


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def _count_since(session: Session, since: datetime, **where) -> int:
    stmt = select(func.count()).select_from(LoginToken).where(LoginToken.created_at >= since)
    if "email" in where:
        stmt = stmt.where(func.lower(LoginToken.email) == where["email"])
    if where.get("ip_hash"):
        stmt = stmt.where(LoginToken.ip_hash == where["ip_hash"])
    return session.execute(stmt).scalar_one()


def _enforce_rate_limits(session: Session, email: str, ip_hash: str | None) -> None:
    now = _now()
    too_many = "Too many sign-in emails just now. Wait a few minutes and try again."
    if _count_since(session, now - timedelta(minutes=15), email=email) >= EMAILS_PER_ADDRESS_15MIN:
        raise RateLimited(too_many)
    if _count_since(session, now - timedelta(hours=1), email=email) >= EMAILS_PER_ADDRESS_HOUR:
        raise RateLimited(too_many)
    if ip_hash:
        per_ip = _count_since(session, now - timedelta(hours=1), ip_hash=ip_hash)
        if per_ip >= EMAILS_PER_IP_HOUR:
            raise RateLimited(too_many)


def issue_token(
    session: Session,
    email: str,
    *,
    purpose: str = PURPOSE_SIGN_IN,
    user_id: int | None = None,
    ip: str | None = None,
    join_section_id: int | None = None,
    join_given_name: str | None = None,
    join_family_name: str | None = None,
) -> tuple[str, str]:
    """Create a pending sign-in. Returns ``(raw_link_token, six_digit_code)`` — the only place
    they exist in the clear. Enforces the rate limits (raises :class:`RateLimited`)."""
    email = email.strip().lower()
    ip_hash = hash_ip(ip)
    _enforce_rate_limits(session, email, ip_hash)

    raw_token = secrets.token_urlsafe(32)
    code = f"{secrets.randbelow(1_000_000):06d}"
    token = LoginToken(
        email=email,
        user_id=user_id,
        purpose=purpose,
        token_hash=_hash_token(raw_token),
        code_hash=_hash_code(code),
        ip_hash=ip_hash,
        join_section_id=join_section_id,
        join_given_name=join_given_name,
        join_family_name=join_family_name,
        expires_at=_now() + timedelta(minutes=TOKEN_TTL_MINUTES),
    )
    session.add(token)
    session.flush()
    return raw_token, code


def issue_staff_code(session: Session, *, email: str, user_id: int | None) -> str:
    """A staff-issued code (I2.6): valid 30 minutes, shown once, no link. Bypasses the email
    rate limits because staff, not the address, asked for it."""
    email = email.strip().lower()
    code = f"{secrets.randbelow(1_000_000):06d}"
    token = LoginToken(
        email=email,
        user_id=user_id,
        purpose=PURPOSE_STAFF_CODE,
        token_hash=None,
        code_hash=_hash_code(code),
        ip_hash=None,
        expires_at=_now() + timedelta(minutes=STAFF_CODE_TTL_MINUTES),
    )
    session.add(token)
    session.flush()
    return code


def find_valid_link(session: Session, raw_token: str) -> LoginToken | None:
    """The token behind a link, if it is unconsumed and unexpired. Does not consume it — a mail
    scanner may open the link first (E1), so GET must be safe."""
    token = session.scalars(
        select(LoginToken).where(LoginToken.token_hash == _hash_token(raw_token))
    ).one_or_none()
    if token is None or token.consumed_at is not None or token.expires_at <= _now():
        return None
    return token


def consume_link(session: Session, raw_token: str) -> LoginToken | None:
    token = find_valid_link(session, raw_token)
    if token is None:
        return None
    token.consumed_at = _now()
    session.flush()
    return token


def consume_code(session: Session, email: str, code: str) -> LoginToken | None:
    """Check a six-digit code against the latest live token for the address. Costs one attempt;
    raises :class:`CodeLocked` once five are used."""
    email = email.strip().lower()
    token = session.scalars(
        select(LoginToken)
        .where(
            func.lower(LoginToken.email) == email,
            LoginToken.consumed_at.is_(None),
            LoginToken.expires_at > _now(),
        )
        .order_by(LoginToken.created_at.desc())
    ).first()
    if token is None:
        return None
    if token.code_attempts >= MAX_CODE_ATTEMPTS:
        raise CodeLocked("Too many attempts. Ask for a new code.")
    token.code_attempts += 1
    session.flush()
    if hmac.compare_digest(token.code_hash, _hash_code(code)):
        token.consumed_at = _now()
        session.flush()
        return token
    return None  # a miss; the top guard locks once the fifth attempt is used


#: Copy for the two misses worth naming. Kept here beside :class:`CodeLocked`, which carries its
#: own message for the same reason: the caller should not have to know why a code failed.
CODE_ALREADY_USED = (
    "That code has already been used. If you were signing in, reload the page — you may "
    "already be signed in."
)
CODE_EXPIRED = "That code has expired. Ask for a new one."


def explain_miss(session: Session, email: str, code: str) -> str | None:
    """Why a code missed — but only when the code is demonstrably theirs.

    :func:`consume_code` returns ``None`` for three different states, and the sign-in page
    reported all of them as a mismatch. A correct code submitted twice was answered "that code
    did not match", which sends someone to re-check a code that was right.

    Returns ``None`` unless the entered code matches a token for this address, so a guess learns
    nothing — not even whether a sign-in is pending (E1). Someone who types a correct code
    already holds it, so naming its state tells them nothing they did not have.
    """
    email = email.strip().lower()
    token = session.scalars(
        select(LoginToken)
        .where(
            func.lower(LoginToken.email) == email,
            LoginToken.code_hash == _hash_code(code),
        )
        .order_by(LoginToken.created_at.desc())
    ).first()
    if token is None:
        return None
    if token.consumed_at is not None:
        return CODE_ALREADY_USED
    if token.expires_at <= _now():
        return CODE_EXPIRED
    return None


def purge_expired(session: Session) -> int:
    """Delete tokens older than 30 days (OPS-7). Runs whenever someone signs in."""
    cutoff = _now() - timedelta(days=PURGE_AFTER_DAYS)
    return session.execute(
        delete(LoginToken).where(LoginToken.created_at < cutoff)
    ).rowcount
