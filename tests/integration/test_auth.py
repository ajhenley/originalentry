"""Magic-link + code sign-in (T9, E1–E4).

Token-level: only hashes are stored, a link/code is single-use and expiring, the code caps at five
attempts, and the email is rate-limited. HTTP: a GET on the link is scanner-safe (consumes
nothing), the POST behind it signs in, the code path signs in, an unknown address gets the same
response with no email sent, joining by code creates the account, and revoke signs every device out.
"""

from datetime import UTC, datetime, timedelta

import pytest
from originalentry.auth import email as email_module
from originalentry.auth import tokens
from originalentry.models import Enrollment, LoginToken, Section, User
from sqlalchemy import func, select

pytestmark = pytest.mark.db


@pytest.fixture
def mail(app):
    cfg = app.extensions["originalentry_config"]
    before = cfg.EMAIL_BACKEND
    cfg.EMAIL_BACKEND = "memory"
    email_module.SENT.clear()
    try:
        yield email_module.SENT
    finally:
        cfg.EMAIL_BACKEND = before
        email_module.SENT.clear()


def _student(session, email="stu@example.edu"):
    user = User(email=email, role="student", given_name="Sam", family_name="Student")
    session.add(user)
    session.flush()
    return user


def _latest_token(session, email):
    return session.scalars(
        select(LoginToken).where(func.lower(LoginToken.email) == email.lower())
        .order_by(LoginToken.created_at.desc(), LoginToken.id.desc())
    ).first()


# ── token service (E2) ───────────────────────────────────────────────────────────────────

def test_issue_stores_only_hashes(session):
    raw, code = tokens.issue_token(session, "Person@Example.edu", ip="203.0.113.7")
    row = _latest_token(session, "person@example.edu")
    assert row.email == "person@example.edu"          # normalised
    assert row.token_hash and row.token_hash != raw     # a hash, not the token
    assert row.code_hash and row.code_hash != code      # a hash, not the code
    assert row.ip_hash and "203.0.113.7" not in row.ip_hash  # HMAC, never the raw IP
    assert len(code) == 6 and code.isdigit()


def test_link_is_single_use(session):
    raw, _ = tokens.issue_token(session, "a@example.edu")
    assert tokens.find_valid_link(session, raw) is not None
    assert tokens.consume_link(session, raw) is not None
    assert tokens.find_valid_link(session, raw) is None   # consumed
    assert tokens.consume_link(session, raw) is None       # cannot be reused


def test_expired_link_is_invalid(session):
    raw, _ = tokens.issue_token(session, "a@example.edu")
    _latest_token(session, "a@example.edu").expires_at = datetime.now(UTC) - timedelta(minutes=1)
    session.flush()
    assert tokens.find_valid_link(session, raw) is None


def test_code_attempts_lock_after_five(session):
    tokens.issue_token(session, "a@example.edu")
    for _ in range(5):
        assert tokens.consume_code(session, "a@example.edu", "000000") is None
    with pytest.raises(tokens.CodeLocked):
        tokens.consume_code(session, "a@example.edu", "000000")


def test_right_code_consumes(session):
    _, code = tokens.issue_token(session, "a@example.edu")
    row = tokens.consume_code(session, "a@example.edu", code)
    assert row is not None and row.consumed_at is not None
    assert tokens.consume_code(session, "a@example.edu", code) is None  # already used


def test_email_is_rate_limited(session):
    for _ in range(tokens.EMAILS_PER_ADDRESS_15MIN):
        tokens.issue_token(session, "a@example.edu", ip="203.0.113.1")
    with pytest.raises(tokens.RateLimited):
        tokens.issue_token(session, "a@example.edu", ip="203.0.113.1")


def test_purge_removes_old_tokens(session):
    tokens.issue_token(session, "old@example.edu")
    _latest_token(session, "old@example.edu").created_at = datetime.now(UTC) - timedelta(days=40)
    session.flush()
    assert tokens.purge_expired(session) >= 1
    assert _latest_token(session, "old@example.edu") is None


# ── HTTP flow (E1) ───────────────────────────────────────────────────────────────────────

def test_sign_in_sends_a_link_and_code(client, session, mail):
    _student(session, "s1@example.edu")
    resp = client.post("/auth/sign-in", data={"email": "s1@example.edu"})
    assert resp.status_code == 200
    assert "Check your email" in resp.get_data(as_text=True)
    assert len(mail) == 1
    assert mail[0]["to"] == "s1@example.edu" and "/auth/verify/" in mail[0]["link"]


def test_get_link_is_scanner_safe_then_post_signs_in(client, session, mail):
    _student(session, "s2@example.edu")
    client.post("/auth/sign-in", data={"email": "s2@example.edu"})
    token = mail[0]["link"].rsplit("/", 1)[-1]

    # A scanner opening the link (GET) must not consume it.
    assert client.get(f"/auth/verify/{token}").status_code == 200
    assert client.get(f"/auth/verify/{token}").status_code == 200
    assert tokens.find_valid_link(session, token) is not None

    resp = client.post("/auth/verify", data={"token": token})
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/home")
    assert client.get("/home").status_code == 200  # signed in

    # The link is spent now.
    assert "expired" in client.get(f"/auth/verify/{token}").get_data(as_text=True).lower()


def test_code_path_signs_in(client, session, mail):
    _student(session, "s3@example.edu")
    client.post("/auth/sign-in", data={"email": "s3@example.edu"})
    code = mail[0]["code"]
    resp = client.post("/auth/code", data={"email": "s3@example.edu", "code": code})
    assert resp.status_code == 302
    assert client.get("/home").status_code == 200


def test_unknown_address_same_response_no_email(client, session, mail):
    resp = client.post("/auth/sign-in", data={"email": "nobody@example.edu"})
    assert resp.status_code == 200
    assert "Check your email" in resp.get_data(as_text=True)
    assert mail == []  # a stranger is never emailed, but the page looks identical (E1)


def test_join_by_code_creates_account_and_enrols(client, session, mail):
    section = Section(name="Sec 1", join_code="MAPLE7", join_code_active=True)
    session.add(section)
    session.flush()

    resp = client.post("/auth/join", data={
        "code": "maple7", "given_name": "New", "family_name": "Student",
        "email": "new@example.edu",
    })
    assert resp.status_code == 200 and "Check your email" in resp.get_data(as_text=True)
    token = mail[0]["link"].rsplit("/", 1)[-1]
    assert client.post("/auth/verify", data={"token": token}).status_code == 302

    user = session.scalars(
        select(User).where(func.lower(User.email) == "new@example.edu")
    ).one()
    assert user.given_name == "New"
    enrolled = session.scalars(
        select(Enrollment).where(Enrollment.user_id == user.id,
                                 Enrollment.section_id == section.id)
    ).one_or_none()
    assert enrolled is not None


def test_revoke_signs_out_every_device(client, session, app):
    # The session cookie carries "public_id:session_epoch"; the user_loader rejects a stale epoch.
    # Called directly because the loader is the unit under test: through the client it would be
    # one step removed, behind the per-request cache the `client` fixture clears.
    user = _student(session, "rev@example.edu")
    loader = app.login_manager._user_callback
    stale_id = user.get_id()
    assert loader(stale_id) is not None

    user.session_epoch += 1   # what `flask auth revoke` does
    session.flush()
    assert loader(stale_id) is None            # every existing device is signed out
    assert loader(user.get_id()) is not None    # a fresh sign-in still works


# ── Why a code missed (E1-safe) ──────────────────────────────────────────────────────────


def test_a_used_code_says_it_was_used_rather_than_blaming_the_typing(session):
    """The commonest real case: a correct code, submitted twice.

    `consume_code` only looks at unconsumed tokens, so the second submission looks identical to a
    wrong code and the student is told to re-check a code that was right.
    """
    _, code = tokens.issue_token(session, "a@example.edu")
    tokens.consume_code(session, "a@example.edu", code)

    assert "already been used" in tokens.explain_miss(session, "a@example.edu", code)


def test_an_expired_code_says_it_expired(session):
    _, code = tokens.issue_token(session, "a@example.edu")
    token = session.scalars(
        select(LoginToken).where(LoginToken.email == "a@example.edu")
    ).one()
    token.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    session.flush()

    assert "expired" in tokens.explain_miss(session, "a@example.edu", code)


def test_a_wrong_code_is_explained_to_nobody(session):
    """A guess must learn nothing — not even that a sign-in is pending."""
    tokens.issue_token(session, "a@example.edu")

    assert tokens.explain_miss(session, "a@example.edu", "000000") is None


def test_a_guess_cannot_tell_whether_an_address_has_a_pending_sign_in(session):
    """E1: the response must not reveal who is enrolled, or who is mid-sign-in.

    This is the assertion that stops a well-meaning fix from turning the message into an
    address-enumeration oracle.
    """
    tokens.issue_token(session, "pending@example.edu")

    with_token = tokens.explain_miss(session, "pending@example.edu", "000000")
    without_token = tokens.explain_miss(session, "nobody@example.edu", "000000")

    assert with_token == without_token is None


def test_submitting_a_code_twice_says_it_was_used_not_that_it_was_wrong(client, session, mail):
    """The bug a real student hit: the code was right, the page said it was not.

    Submitting twice — a refresh, a back button, a double click — consumed the token on the first
    POST, and the second was answered "That code did not match", sending them to re-check a code
    that had just worked.
    """
    _student(session, "s9@example.edu")
    client.post("/auth/sign-in", data={"email": "s9@example.edu"})
    code = mail[0]["code"]
    assert client.post("/auth/code", data={"email": "s9@example.edu", "code": code}).status_code == 302

    again = client.post("/auth/code", data={"email": "s9@example.edu", "code": code})

    body = again.get_data(as_text=True)
    assert "already been used" in body
    assert "did not match" not in body


def test_a_wrong_code_still_says_only_that_it_did_not_match(client, session, mail):
    """The generic message must survive for a guess, or the fix becomes an enumeration oracle."""
    _student(session, "s10@example.edu")
    client.post("/auth/sign-in", data={"email": "s10@example.edu"})

    resp = client.post("/auth/code", data={"email": "s10@example.edu", "code": "000000"})

    body = resp.get_data(as_text=True)
    assert "did not match" in body
    assert "already been used" not in body
