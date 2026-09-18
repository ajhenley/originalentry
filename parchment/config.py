"""Configuration (T13 config variables, T12 engine settings, E3 sessions).

All configuration comes from the environment. The pooler-safe engine settings (server-side
prepared statements off, pre-ping, short recycle) are what let one code path work through Neon's
transaction-mode pooler (T12).
"""

from __future__ import annotations

import os
from datetime import timedelta


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def normalize_db_url(url: str) -> str:
    """Coerce any Postgres URL to the ``postgresql+psycopg://`` scheme (psycopg 3, T12).

    Heroku hands out ``postgres://``; some tools emit ``jdbc:postgresql://``. All map to the
    one driver this app is built and tested on.
    """
    if not url:
        return url
    if url.startswith("jdbc:"):
        url = url[len("jdbc:") :]
    if url.startswith("postgresql+"):
        return url
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


class ConfigError(RuntimeError):
    """Raised at startup for a configuration that must never reach production."""


class Config:
    def __init__(self, env: dict[str, str] | None = None):
        e = env if env is not None else os.environ

        self.APP_ENV = e.get("APP_ENV", "development")
        self.IS_PRODUCTION = self.APP_ENV == "production"

        self.SECRET_KEY = e.get("SECRET_KEY", "" if self.IS_PRODUCTION else "dev-secret")
        if self.IS_PRODUCTION and not self.SECRET_KEY:
            raise ConfigError("SECRET_KEY is required in production.")

        self.SQLALCHEMY_DATABASE_URI = normalize_db_url(e.get("DATABASE_URL", ""))
        self.DATABASE_URL_DIRECT = normalize_db_url(
            e.get("DATABASE_URL_DIRECT", "") or self.SQLALCHEMY_DATABASE_URI
        )
        # Migrations, pack import, purge and backups use the direct (non-pooled) endpoint (T12).
        # The release phase and CLI set PARCHMENT_USE_DIRECT_DB=1.
        if _bool("PARCHMENT_USE_DIRECT_DB", False):
            self.SQLALCHEMY_DATABASE_URI = self.DATABASE_URL_DIRECT
        self.SQLALCHEMY_TRACK_MODIFICATIONS = False
        # T12: pool 5 + overflow 2 per worker, pre-ping, recycle 300s, 10s connect timeout,
        # server-side prepared statements OFF (unsafe through the transaction-mode pooler).
        self.SQLALCHEMY_ENGINE_OPTIONS = {
            "pool_size": 5,
            "max_overflow": 2,
            "pool_pre_ping": True,
            "pool_recycle": 300,
            "connect_args": {"prepare_threshold": None, "connect_timeout": 10},
        }

        # Email (E5/E6). The console backend is refused in production.
        self.EMAIL_BACKEND = e.get("EMAIL_BACKEND", "console")
        self.MAIL_FROM = e.get("MAIL_FROM", "")
        self.MAIL_REPLY_TO = e.get("MAIL_REPLY_TO", "")
        self.RESEND_API_KEY = e.get("RESEND_API_KEY", "")
        self.STAGING_EMAIL_ALLOWLIST = e.get("STAGING_EMAIL_ALLOWLIST", "")
        if self.IS_PRODUCTION and self.EMAIL_BACKEND == "console":
            raise ConfigError("EMAIL_BACKEND=console is refused when APP_ENV=production (E5).")

        self.APP_BASE_URL = e.get("APP_BASE_URL", "http://localhost:5000")
        self.COURSE_TZ = e.get("COURSE_TZ", "America/Los_Angeles")
        self.SENTRY_DSN = e.get("SENTRY_DSN", "")

        # Sessions and cookies (E3).
        self.SESSION_COOKIE_HTTPONLY = True
        self.SESSION_COOKIE_SAMESITE = "Lax"
        self.SESSION_COOKIE_SECURE = self.IS_PRODUCTION or _bool("FORCE_SECURE_COOKIES", False)
        # Default is a browser session with a 2-hour idle timeout; the "keep me signed in"
        # 14-day option is applied per-login by the auth blueprint via the remember cookie.
        self.PERMANENT_SESSION_LIFETIME = timedelta(hours=2)
        self.REMEMBER_COOKIE_DURATION = timedelta(days=14)
        self.REMEMBER_COOKIE_HTTPONLY = True
        self.REMEMBER_COOKIE_SAMESITE = "Lax"
        self.REMEMBER_COOKIE_SECURE = self.SESSION_COOKIE_SECURE

        # CSRF on every POST, with NO time limit (a form open for hours must still save).
        self.WTF_CSRF_TIME_LIMIT = None

    def as_flask_mapping(self) -> dict[str, object]:
        """The subset Flask/extensions read via app.config."""
        return {
            k: v
            for k, v in vars(self).items()
            if k.isupper()
        }


def load_config(env: dict[str, str] | None = None) -> Config:
    return Config(env)
