"""Error pages (Part I §4). Each says what happened, whether the student's work is safe, and
what to do next. "Something went wrong" is banned. Templates arrive in phase 8; for now these
render minimal, honest text.
"""

from __future__ import annotations

from flask import Flask
from flask_wtf.csrf import CSRFError
from werkzeug.exceptions import HTTPException

# code -> (heading, what to do). Every message states that saved work is safe.
_PAGES: dict[int, tuple[str, str]] = {
    400: ("This request could not be read.", "Go back and try again. Your saved work is safe."),
    403: ("You are not signed in for this.", "Sign in again. Your saved work is safe."),
    404: ("This page is not here.", "Check the address or go back. Your saved work is safe."),
    405: ("That action is not allowed here.", "Go back and try again. Your saved work is safe."),
    413: ("That upload is too large.", "Use a smaller file. Your saved work is safe."),
    429: ("Too many attempts just now.", "Wait a minute and try again."),
    500: (
        "The server had a problem with this request.",
        "Your saved work is safe. Try again in a moment.",
    ),
}


def _render(code: int) -> tuple[str, int]:
    heading, guidance = _PAGES.get(code, _PAGES[500])
    body = (
        f"<!doctype html><html lang=en><head><meta charset=utf-8>"
        f"<title>{code}</title></head><body>"
        f"<h1>{heading}</h1><p>{guidance}</p></body></html>"
    )
    return body, code


def init_errors(app: Flask) -> None:
    @app.errorhandler(CSRFError)
    def _csrf(_e):
        body = (
            "<!doctype html><html lang=en><head><meta charset=utf-8><title>Session</title></head>"
            "<body><h1>This page sat open too long to submit safely.</h1>"
            "<p>Reload the page and try again. Your saved work is safe.</p></body></html>"
        )
        return body, 400

    @app.errorhandler(HTTPException)
    def _http(e: HTTPException):
        code = e.code or 500
        if code in _PAGES:
            return _render(code)
        return _render(500 if code >= 500 else 400)

    @app.errorhandler(Exception)
    def _unhandled(_e):
        return _render(500)
