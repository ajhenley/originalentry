"""Security headers and CSP (T11). No extra library.

A per-request nonce lets templates load their own CSS/JS without ever using an inline ``style``
attribute or inline handler — the CSP forbids those, and a guard test scans templates for them.
"""

from __future__ import annotations

import secrets

from flask import Flask, g, request


def _csp(nonce: str) -> str:
    return (
        "default-src 'self'; "
        f"script-src 'self' 'nonce-{nonce}'; "
        f"style-src 'self' 'nonce-{nonce}'; "
        "img-src 'self' data:; "
        "frame-ancestors 'none'; "
        "form-action 'self'; "
        "base-uri 'self'"
    )


def init_security(app: Flask) -> None:
    @app.before_request
    def _assign_nonce() -> None:
        g.csp_nonce = secrets.token_urlsafe(16)

    @app.context_processor
    def _inject_nonce() -> dict:
        return {"csp_nonce": getattr(g, "csp_nonce", "")}

    @app.after_request
    def _set_headers(response):
        response.headers.setdefault("Content-Security-Policy", _csp(getattr(g, "csp_nonce", "")))
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        # HSTS only over TLS (never on plain-http localhost).
        if request.is_secure:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response
