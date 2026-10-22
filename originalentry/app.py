"""The application factory (T3). Kept out of ``__init__`` so the pure engine imports stay
Flask-free. Imported lazily by the web process, the CLI and the tests.
"""

from __future__ import annotations

import os
import pathlib

from flask import Flask, jsonify, redirect
from sqlalchemy import text
from werkzeug.middleware.proxy_fix import ProxyFix

from . import messages
from .config import load_config
from .errors import init_errors
from .extensions import csrf, db, login_manager, migrate
from .security import init_security

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load_dotenv() -> None:
    """Load ``.env`` into the process env for local dev and tests (no python-dotenv dependency).

    **Overrides** values already in the environment, and does nothing in production. The override
    is deliberate -- see the comment on the assignment below -- and it means an exported
    DATABASE_URL does not take effect, which is why the test harness selects its database through
    ``load_config(env=...)`` rather than by exporting one (tests/database_target.py).
    """
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
    app.extensions["originalentry_config"] = cfg

    if not app.config["SCOPED_VISIBILITY"]:
        app.logger.warning(
            "SCOPED_VISIBILITY is off: every staff member can see every student's work.")

    # Error monitoring (T13). The config has always read SENTRY_DSN; without this nothing was ever
    # sent, so a production 500 was invisible until a student reported it. Initialised only when a
    # DSN is set, so dev and tests send nothing. send_default_pii stays off: this app's users are
    # students, and an answer key must never ride out on a traceback (D6).
    if cfg.SENTRY_DSN:
        import sentry_sdk
        from sentry_sdk.integrations.flask import FlaskIntegration

        sentry_sdk.init(
            dsn=cfg.SENTRY_DSN,
            integrations=[FlaskIntegration()],
            environment=cfg.APP_ENV,
            send_default_pii=False,
            traces_sample_rate=0.0,
        )

    # Heroku router terminates TLS; trust one proxy hop so url_for builds https links.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    # Import models before init so metadata is populated for Flask-Migrate.
    from . import models  # noqa: F401

    db.init_app(app)
    migrate.init_app(app, db, directory=str(_REPO_ROOT / "migrations"))
    csrf.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.sign_in_form"
    # basic, not strong: strong signs students out when their network changes (E3).
    login_manager.session_protection = "basic"

    _register_login(app)
    _register_jinja(app)
    _register_blueprints(app)
    _register_cli(app)
    init_security(app)
    init_errors(app)
    _register_health(app)
    _register_audit(app)

    return app


def _register_audit(app: Flask) -> None:
    """Record every privileged request and every sign-in attempt into the durable AuditLog.

    One hook is the whole of the staff/auth capture: it fires after the view, so it sees the final
    status and -- for a sign-in -- the user the request authenticated as. Students' own traffic is
    deliberately not recorded here; their light, purgeable telemetry stays in activity_event
    (services/activity.py), which is the retention split the feature was scoped around.

    A teacher's own practice copy is the one workspace a staff request may be in and still not be
    recorded: practice traffic is workspace traffic, which this trail keeps out by design (see
    ``audit.should_audit``). The answer is read off ``g.workspace``, which
    ``decorators.workspace_view`` sets and nothing else does, so it is absent on every request
    that is not a page of somebody's books -- and ``workspaces.is_own_practice`` is null-safe on
    both arguments for exactly this call site. That matters more here than anywhere: an
    ``AttributeError`` raised inside this hook would be swallowed by the ``except`` below, and the
    whole durable trail would silently stop recording.

    Logging never breaks a response: a failure to write the row is rolled back and swallowed. The
    row is committed on its own, after the view has committed its work.
    """
    from flask import g, request
    from flask_login import current_user

    from .services import audit
    from .workspaces import is_own_practice

    @app.after_request
    def _audit(response):
        try:
            role = getattr(current_user, "role", None) if current_user.is_authenticated else None
            if not audit.should_audit(
                request.blueprint, request.endpoint, role, current_user.is_authenticated,
                own_practice=is_own_practice(getattr(g, "workspace", None), current_user),
            ):
                return response
            audit.record(
                db.session,
                action=request.endpoint or request.path,
                actor=current_user if current_user.is_authenticated else None,
                method=request.method,
                status=response.status_code,
                ip=request.remote_addr,
                # Route parameters only -- ids and slugs, never a form body or a typed credential.
                detail={"params": request.view_args} if request.view_args else {},
            )
            db.session.commit()
        except Exception:  # logging must never turn a good response into an error
            db.session.rollback()
        return response


def _register_cli(app: Flask) -> None:
    from .cli import register_cli

    register_cli(app)


def _register_jinja(app: Flask) -> None:
    from . import money
    from .presentation import kind_label

    app.jinja_env.filters["money"] = money.format_cents
    app.jinja_env.filters["dollars"] = money.format_dollars
    app.jinja_env.filters["kind_label"] = kind_label

    def _account_workspaces():
        from flask_login import current_user

        from .decorators import STAFF_ROLES, workspaces_of

        if not current_user.is_authenticated or current_user.role in STAFF_ROLES:
            return []
        return workspaces_of(current_user.id)

    def _account_label() -> str:
        """What the menu is called before it is opened.

        It names what is inside, because a trigger showing only somebody's name does not read as
        a menu of their books. Staff have no workspaces, so theirs says something else that is
        true; who is signed in moves inside the menu, where it informs instead of disguising.
        """
        from flask_login import current_user

        from .decorators import STAFF_ROLES

        if not current_user.is_authenticated:
            return ""
        return "Account" if current_user.role in STAFF_ROLES else "Your workspaces"

    def _viewer_is_staff() -> bool:
        # A computed boolean rather than the frozenset: templates ask "is this viewer staff?" and
        # must not carry an opinion about which roles those are (decorators.STAFF_ROLES owns it).
        from flask_login import current_user

        from .decorators import STAFF_ROLES

        return bool(current_user.is_authenticated and current_user.role in STAFF_ROLES)

    def _viewer_is_admin() -> bool:
        # The same rule as _viewer_is_staff, for the same reason: a template asks "may this viewer
        # do the cohort-wide things?" and must not carry an opinion about which roles those are
        # (decorators.ADMIN_ROLES owns it).
        from flask_login import current_user

        from .decorators import ADMIN_ROLES

        return bool(current_user.is_authenticated and current_user.role in ADMIN_ROLES)

    @app.context_processor
    def _inject_workspace_context():
        # The workspace decorator sets these on g; expose them to base/layout templates.
        from flask import g

        from .models import KIND_PROBLEM_SET

        return {
            "workspace": getattr(g, "workspace", None),
            "company": getattr(g, "company", None),
            "read_only": getattr(g, "read_only", False),
            # Whether these books are the viewer's own practice copy. Separate from read_only
            # because a live practice copy is writable: the two notices answer different
            # questions and a practice copy that is also archived shows both.
            "own_practice": getattr(g, "own_practice", False),
            "own_practice_message": messages.OWN_PRACTICE_COPY,
            # Which kind of pack this workspace holds, so a layout can offer the right navigation
            # rather than links decorators._fence would 404.
            "is_problem_set": getattr(
                getattr(g, "content_pack", None), "kind", None) == KIND_PROBLEM_SET,
            "variant_code": getattr(g, "variant_code", None),
            "read_only_message": getattr(g, "read_only_message", None),
            "save_messages": messages.save_banner_strings(),
            # The account menu appears in every chrome, so its data lives here rather than in
            # each view. It queries only for a signed-in student (D6 rule 3).
            "my_workspaces": _account_workspaces(),
            "account_label": _account_label(),
            "is_staff": _viewer_is_staff(),
            "is_admin": _viewer_is_admin(),
            "grading_messages": messages.grading_batch_strings(),
            "switch_targets": getattr(g, "switch_targets", []),
            # The date the public documents carry, in one place so they cannot disagree.
            "policy_updated": "19 September 2026",
        }


def _register_blueprints(app: Flask) -> None:
    from .auth import bp as auth_bp
    from .public import bp as public_bp
    from .staff import bp as staff_bp
    from .student import bp as student_bp

    app.register_blueprint(public_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(student_bp)
    app.register_blueprint(staff_bp)


def _register_login(app: Flask) -> None:
    from .models import User

    @login_manager.unauthorized_handler
    def unauthorized():
        """A save from a session that has expired gets 401, not the sign-in page (T7.4).

        The script keeps what the student typed, sends them to sign in, and puts it back
        afterwards. A page request still redirects, as it always did.
        """
        from flask import make_response, request, url_for

        next_url = request.full_path if request.method == "GET" else request.referrer
        sign_in = url_for("auth.sign_in_form", next=next_url)
        if request.headers.get("X-OriginalEntry-Save"):
            response = make_response("", 401)
            response.headers["X-Redirect-To"] = sign_in
            return response
        return redirect(sign_in)

    @login_manager.user_loader
    def load_user(token: str):
        # token is "public_id:session_epoch" — the epoch invalidates every device on revoke.
        public_id, _, epoch = token.partition(":")
        user = db.session.execute(
            db.select(User).filter_by(public_id=public_id)
        ).scalar_one_or_none()
        if user is None or str(user.session_epoch) != epoch:
            return None
        # One chokepoint for every live session, whatever cookie is carrying it. Returning None
        # here only kills the session; auth.views._complete_sign_in is what refuses a *new*
        # sign-in with a reason, so nobody is bounced without being told why.
        if user.deactivated_at is not None:
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
