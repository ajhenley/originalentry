"""The application factory (T3). Kept out of ``__init__`` so the pure engine imports stay
Flask-free. Imported lazily by the web process, the CLI and the tests.
"""

from __future__ import annotations

import os
import pathlib

from flask import Flask, jsonify
from sqlalchemy import text
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import load_config
from .errors import init_errors
from .extensions import csrf, db, login_manager, migrate
from .security import init_security

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load_dotenv() -> None:
    """Load ``.env`` into the process env for local dev and tests (no python-dotenv dependency).
    Never overrides a value already set, and does nothing in production."""
    if os.environ.get("APP_ENV") == "production":
        return
    path = _REPO_ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        # In dev/test the .env file is the source of truth and overrides a stale ambient value
        # (e.g. a DATABASE_URL left exported in the shell). Production never reaches here.
        os.environ[key.strip()] = value.strip()


def create_app(config=None) -> Flask:
    _load_dotenv()
    app = Flask(__name__)

    cfg = config or load_config()
    app.config.update(cfg.as_flask_mapping())
    app.extensions["parchment_config"] = cfg

    # Heroku router terminates TLS; trust one proxy hop so url_for builds https links.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    # Import models before init so metadata is populated for Flask-Migrate.
    from . import models  # noqa: F401

    db.init_app(app)
    migrate.init_app(app, db, directory=str(_REPO_ROOT / "migrations"))
    csrf.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.sign_in_form"

    _register_login(app)
    _register_jinja(app)
    _register_blueprints(app)
    init_security(app)
    init_errors(app)
    _register_health(app)

    return app


def _register_jinja(app: Flask) -> None:
    from . import money
    from .presentation import kind_label

    app.jinja_env.filters["money"] = money.format_cents
    app.jinja_env.filters["dollars"] = money.format_dollars
    app.jinja_env.filters["kind_label"] = kind_label

    @app.context_processor
    def _inject_workspace_context():
        # The workspace decorator sets these on g; expose them to base/layout templates.
        from flask import g

        return {
            "workspace": getattr(g, "workspace", None),
            "company": getattr(g, "company", None),
            "read_only": getattr(g, "read_only", False),
            "read_only_message": getattr(g, "read_only_message", None),
        }


def _register_blueprints(app: Flask) -> None:
    from .auth import bp as auth_bp
    from .student import bp as student_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(student_bp)


def _register_login(app: Flask) -> None:
    from .models import User

    @login_manager.user_loader
    def load_user(token: str):
        # token is "public_id:session_epoch" — the epoch invalidates every device on revoke.
        public_id, _, epoch = token.partition(":")
        user = db.session.execute(
            db.select(User).filter_by(public_id=public_id)
        ).scalar_one_or_none()
        if user is None or str(user.session_epoch) != epoch:
            return None
        return user


def _register_health(app: Flask) -> None:
    @app.get("/healthz")
    def healthz():
        # SELECT 1 with a short timeout; 200 or 503, no details (OPS-1).
        try:
            db.session.execute(text("SELECT 1"))
            return jsonify(status="ok"), 200
        except Exception:
            return jsonify(status="unavailable"), 503
