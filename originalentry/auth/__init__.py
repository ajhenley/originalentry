"""The auth blueprint. Magic-link + six-digit-code sign-in (T9) lands in the auth phase; for now
a development-only sign-in establishes a session so the student screens can be used and tested."""

from .views import bp

__all__ = ["bp"]
