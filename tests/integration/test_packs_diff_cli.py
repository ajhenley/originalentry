"""What a new version would do to the refs students hold, before it is imported anywhere.

The clinic's v1-to-v2 rebuild renamed 8 of 17 shared refs and flipped 2 triage answers, and
nothing said so until someone went looking afterwards. This is the looking, made cheap.
"""

from __future__ import annotations

import copy
import secrets

import pytest
from originalentry.packs import schema
from originalentry.packs.importer import import_content

from tests.packs import testco_alpha

pytestmark = pytest.mark.db


@pytest.fixture(autouse=True)
def _cli_shares_the_session_connection(app, session):
    """Route `db.session` -- which `flask packs diff` reads through its own, CLI-pushed app
    context -- onto this test's connection, so what `session` writes here is visible to the CLI
    invocation and nothing escapes the per-test rollback.

    `app.test_cli_runner().invoke(...)` runs the command inside a *new* Flask app context
    (`with_appcontext` pushes one per invocation), and flask-sqlalchemy scopes `db.session` by
    app-context id, so the CLI's session is a different object from the `session` fixture's no
    matter what. Without this, the CLI's session binds to the real pooled engine, opens its own
    connection, and never sees data this test imported on `session`'s connection -- which is
    never actually committed to Postgres (the fixture's `session.commit()` only releases a
    SAVEPOINT inside the still-open outer transaction). The symptom was `ClickException: No
    company '...' in the catalogue.` even though the import had just happened.

    This mirrors `tests/conftest.py`'s `client` fixture, which solves the identical problem for
    requests through the Flask test client, by overriding the engine the session factory binds
    to for the default bind key. A CLI invocation doesn't need that fixture's other job (building
    a `FlaskClient` and swapping in `_Client`), just this part of it.
    """
    engines = app.extensions["sqlalchemy"]._app_engines[app]
    original = dict(engines)
    engines[None] = session.connection()
    try:
        yield
    finally:
        engines.clear()
        engines.update(original)


def _import(session, slug, version, rename=None):
    data = copy.deepcopy(testco_alpha.PACK)
    data["company"]["slug"] = slug
    data["company"]["name"] = slug
    data["version"] = version
    if rename:
        ref, display_ref = rename
        for document in data["documents"]:
            if document["ref"] == ref:
                document["display_ref"] = display_ref
    return import_content(session, schema.load_pack(data), source_sha256=secrets.token_hex(32))


def test_the_report_names_a_ref_that_changed_meaning(session, app):
    slug = f"diff-{secrets.token_hex(3)}"
    first = _import(session, slug, 1)
    ref = first.documents[0].ref if hasattr(first, "documents") else "INV-1"
    _import(session, slug, 2, rename=(ref, "A different artefact"))
    session.commit()

    result = app.test_cli_runner().invoke(
        args=["packs", "diff", "--company", slug, "--from", "1", "--to", "2"]
    )

    assert result.exit_code == 0, result.output
    assert ref in result.output
    assert "A different artefact" in result.output


def test_an_identical_rebuild_reports_nothing_changed(session, app):
    slug = f"same-{secrets.token_hex(3)}"
    _import(session, slug, 1)
    _import(session, slug, 2)
    session.commit()

    result = app.test_cli_runner().invoke(
        args=["packs", "diff", "--company", slug, "--from", "1", "--to", "2"]
    )

    assert result.exit_code == 0, result.output
    assert "no document changed what it denotes" in result.output


def test_a_version_that_is_not_there_is_refused_with_a_sentence(session, app):
    slug = f"absent-{secrets.token_hex(3)}"
    _import(session, slug, 1)
    session.commit()

    result = app.test_cli_runner().invoke(
        args=["packs", "diff", "--company", slug, "--from", "1", "--to", "9"]
    )

    assert result.exit_code != 0
    assert "version 9" in result.output
