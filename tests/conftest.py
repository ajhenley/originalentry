"""The database test harness. Real Postgres (Neon), because triggers, composite keys and locks
are part of the design (T17.1). Every test runs inside one transaction that is rolled back, so
nothing persists to the database.

It lives at the top of ``tests/`` because the golden tests need it too: A3 is proved twice, once
against the pure engine and once against a workspace read back out of the database.
"""

import pytest
from flask import g, has_app_context
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
        # This harness holds one app context open for the whole test, and Flask reuses it for
        # each request rather than pushing a fresh one. Flask-Login caches the loaded user on
        # ``g``, so without this a second sign-in in the same test would be ignored.
        if has_app_context():
            g.pop("_login_user", None)


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

    db.session.remove()
    db.session.registry.set(session)
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    app.test_client_class = _Client

    try:
        yield app.test_client()
    finally:
        db.session.registry.clear()
        engines.clear()
        engines.update(original)
        app.config.update(TESTING=False, WTF_CSRF_ENABLED=True)
