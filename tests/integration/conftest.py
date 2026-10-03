"""Shared fixtures for the integration suite (as opposed to tests/conftest.py's app/session/
client, which the whole suite needs).
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _cli_shares_the_session_connection(app, session):
    """Route `db.session` -- which a Flask CLI command reads through its own, CLI-pushed app
    context -- onto this test's connection, so what `session` writes here is visible to the CLI
    invocation and nothing escapes the per-test rollback.

    `app.test_cli_runner().invoke(...)` runs the command inside a *new* Flask app context
    (`AppGroup` wraps every subcommand in `with_appcontext`, which pushes one per invocation), and
    flask-sqlalchemy scopes `db.session` by app-context id, so the CLI's session is a different
    object from the `session` fixture's no matter what. Without this, the CLI's session binds to
    the real pooled engine, opens its own connection, and never sees data this test imported on
    `session`'s connection -- which is never actually committed to Postgres (the fixture's own
    `session.commit()` only releases a SAVEPOINT inside the still-open outer transaction). The
    symptom was `ClickException: No company '...' in the catalogue.` even though the import had
    just happened.

    This mirrors `tests/conftest.py`'s `client` fixture, which solves the identical problem for
    requests through the Flask test client, by overriding the engine the session factory binds
    to for the default bind key. A CLI invocation doesn't need that fixture's other job (building
    a `FlaskClient` and swapping in `_Client`), just this part of it.

    Autouse and this generic, rather than imported per module: `flask packs diff` was the first
    caller and `flask packs migrate` is the second, and a thing two Flask CLI test modules need
    identically is the moment promotion was always meant to happen (T2a/T3).
    """
    engines = app.extensions["sqlalchemy"]._app_engines[app]
    original = dict(engines)
    engines[None] = session.connection()
    try:
        yield
    finally:
        engines.clear()
        engines.update(original)
