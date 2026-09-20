"""Sign-in email — the only email the app sends (E5).

One function, one HTTPS POST to Resend, no SDK. The email carries only the link, the code and the
expiry, plus a line to ignore it if you did not ask — no name, no course, no marks. Addresses,
links and codes are never logged in production; the ``console`` backend (development and tests)
is refused at startup when ``APP_ENV=production`` (see ``config``).
"""

from __future__ import annotations

import requests
from flask import current_app

RESEND_ENDPOINT = "https://api.resend.com/emails"
TIMEOUT_SECONDS = 10

# The ``memory`` backend appends here so tests can read what would have been sent.
SENT: list[dict] = []


class EmailError(Exception):
    """The email could not be sent. The caller shows the E5 "try again" message; nothing leaks."""


def _text_body(link: str, code: str, expires_minutes: int) -> str:
    return (
        "Sign in to Original Entry.\n\n"
        f"Open this link:\n{link}\n\n"
        f"Or enter this code: {code}\n\n"
        f"The link and the code both expire in {expires_minutes} minutes and can be used once.\n\n"
        "If you did not ask for this, ignore it.\n"
    )


def _html_body(link: str, code: str, expires_minutes: int) -> str:
    return (
        f'<p>Sign in to Original Entry.</p>'
        f'<p><a href="{link}">Open this link</a></p>'
        f"<p>Or enter this code: <strong>{code}</strong></p>"
        f"<p>The link and the code both expire in {expires_minutes} minutes and "
        "can be used once.</p>"
        "<p>If you did not ask for this, ignore it.</p>"
    )


def send_sign_in_email(to: str, link: str, code: str, *, expires_minutes: int = 15) -> None:
    cfg = current_app.extensions["originalentry_config"]
    backend = cfg.EMAIL_BACKEND

    allowlist = {
        a.strip().lower()
        for a in (cfg.STAGING_EMAIL_ALLOWLIST or "").split(",")
        if a.strip()
    }
    if allowlist and to.lower() not in allowlist:
        raise EmailError("This address is not on the staging allow-list.")

    subject = "Your Original Entry sign-in link"
    text = _text_body(link, code, expires_minutes)

    if backend == "console":
        # Development/tests only. Printed, never the production logger.
        print(f"\n[sign-in email] to {to}\n{text}", flush=True)
    elif backend == "memory":
        SENT.append({"to": to, "link": link, "code": code, "subject": subject})
    elif backend == "resend":
        _send_via_resend(cfg, to, subject, text, _html_body(link, code, expires_minutes))
    else:
        raise EmailError(f"Unknown email backend: {backend!r}")


def _send_via_resend(cfg, to: str, subject: str, text: str, html: str) -> None:
    if not cfg.RESEND_API_KEY or not cfg.MAIL_FROM:
        raise EmailError("Email is not configured.")
    payload = {
        "from": cfg.MAIL_FROM,
        "to": [to],
        "subject": subject,
        "text": text,
        "html": html,
    }
    if cfg.MAIL_REPLY_TO:
        payload["reply_to"] = cfg.MAIL_REPLY_TO
    try:
        response = requests.post(
            RESEND_ENDPOINT,
            json=payload,
            headers={"Authorization": f"Bearer {cfg.RESEND_API_KEY}"},
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise EmailError("Could not reach the email service.") from exc
    if response.status_code >= 300:
        # Do not include the address or the body in the error (E5).
        raise EmailError(f"The email service refused the message ({response.status_code}).")
