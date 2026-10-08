"""The database test harness. Real Postgres (Neon), because triggers, composite keys and locks
are part of the design (T17.1). Every test runs inside one transaction that is rolled back, so
nothing persists to the database.

It lives at the top of ``tests/`` because the golden tests need it too: A3 is proved twice, once
against the pure engine and once against a workspace read back out of the database.
"""

import pytest
from flask import g
from flask.testing import FlaskClient
from originalentry.app import create_app
from originalentry.extensions import db
from sqlalchemy.orm import Session

pytestmark = pytest.mark.db


@pytest.fixture(scope="session")
def app():
    app = create_app()
    # Safety net: the tests must never send a real email, whatever EMAIL_BACKEND says in .env.
    # The auth tests still override this to "memory" to read what would have been sent.
    app.extensions["originalentry_config"].EMAIL_BACKEND = "memory"
    return app


@pytest.fixture
def session(app):
    with app.app_context():
        connection = db.engine.connect()
        trans = connection.begin()
        # join_transaction_mode="create_savepoint": a service that commits (the write path does)
        # releases a SAVEPOINT rather than the outer transaction, so the teardown rollback still
        # undoes everything and nothing persists to Neon.
        s = Session(bind=connection, expire_on_commit=False,
                    join_transaction_mode="create_savepoint")
        try:
            yield s
        finally:
            s.close()
            if trans.is_active:  # a test may have rolled back after a forced constraint check
                trans.rollback()
            connection.close()


class _Client(FlaskClient):
    """A test client that can sign a user in without going through the dev sign-in form."""

    def sign_in(self, user):
        with self.session_transaction() as flask_session:
            flask_session["_user_id"] = user.get_id()  # "public_id:session_epoch"
            flask_session["_fresh"] = True


@pytest.fixture
def client(app, session):
    """A test client whose requests run on the test's own session, so nothing persists.

    The app and the test share **one** Session: two sessions on one connection each managing their
    own savepoints will fight, and the loser is a teardown that cannot roll back. Because that
    session joins the outer transaction through a SAVEPOINT, a request may commit — the write path
    does — and the teardown rollback still undoes all of it.
    """
    connection = session.connection()
    engines = app.extensions["sqlalchemy"]._app_engines[app]
    original = dict(engines)
    engines[None] = connection

    # Every request inside a test begins with the per-request caches cleared, the way a production
    # request does by getting a fresh app context. This harness holds **one** app context open for
    # the whole test and Flask reuses it per request, so without this hook: Flask-Login answers
    # from the user it cached on ``g`` (flask_login/utils.py:_get_user), and
    # decorators.my_section_ids returns the sections it loaded for whoever was signed in before.
    # Either one silently makes a test vacuous -- sign in as A, act, sign in as B or change A's
    # account, act again, and the second request is answered from the first request's beliefs. A
    # test asserting that a revoked or deactivated session dies passes without the loader ever
    # running. It lives here rather than in each test because a test that forgets it does not
    # fail; it passes, saying nothing.
    #
    # **Exactly these two keys, and never the whole of ``g``.** flask_wtf.generate_csrf also
    # caches on ``g`` (flask_wtf/csrf.py:50) and base.html:7 renders that token into every page.
    # Clearing it per request re-serialises the token through URLSafeTimedSerializer, whose
    # timestamp has one-second resolution, which would turn the byte-for-byte E1 comparison in
    # tests/integration/test_deactivation.py into a timing coin-flip.
    def _fresh_request_caches() -> None:
        g.pop("_login_user", None)       # flask_login's per-context current_user
        g.pop("_my_section_ids", None)   # decorators.my_section_ids

    db.session.remove()
    db.session.registry.set(session)
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    app.test_client_class = _Client

    try:
        # Registered inside the try, so the finally below always removes it again. ``app`` is
        # session-scoped: a hook left behind by a fixture that raised on its way in would stay
        # registered for every later test in the run.
        app.before_request_funcs.setdefault(None, []).append(_fresh_request_caches)
        yield app.test_client()
    finally:
        app.before_request_funcs[None].remove(_fresh_request_caches)
        db.session.registry.clear()
        engines.clear()
        engines.update(original)
        app.config.update(TESTING=False, WTF_CSRF_ENABLED=True)
