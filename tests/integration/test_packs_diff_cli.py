"""What a new version would do to the refs students hold, before it is imported anywhere.

The clinic's v1-to-v2 rebuild renamed 8 of 17 shared refs and flipped 2 triage answers, and
nothing said so until someone went looking afterwards. This is the looking, made cheap.
"""

from __future__ import annotations

import copy
import secrets

import pytest
from originalentry.packs import schema
from originalentry.packs.importer import import_answer_keys, import_content
from sqlalchemy import event

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
    _import(session, slug, 1)
    ref = "INV-1"  # testco_alpha's PACK fixture's first document
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


def _import_with_variants(session, slug, version, *, triage_value):
    """A pack over three variants (A, B, C), each with an answer key that answers the same
    ref's triage question identically within that version -- so a ref that flips between
    versions flips in all three variants at once, and `identity_changes` reports one
    `IdentityChange` per variant.

    This is the shape `test_a_flipped_ref_is_counted_once_not_once_per_variant` needs: every
    test above it uses testco_alpha's single variant, which can never produce more than one
    `IdentityChange` for a flipped ref, and so could never have caught the summary line
    counting flip *events* instead of distinct refs (C1).
    """
    data = copy.deepcopy(testco_alpha.PACK)
    data["company"]["slug"] = slug
    data["company"]["name"] = slug
    data["version"] = version
    data["variants"] = [
        {"code": "A", "label": "Variant A", "drivers": {}},
        {"code": "B", "label": "Variant B", "drivers": {}},
        {"code": "C", "label": "Variant C", "drivers": {}},
    ]
    ob = data["opening_balances"]["A"]
    data["opening_balances"] = {code: ob for code in ("A", "B", "C")}
    pv = import_content(session, schema.load_pack(data), source_sha256=secrets.token_hex(32))
    keys = {
        code: schema.load_answer_key(
            {"variant": code, "triage": {"INV-1": triage_value, "INV-2": True}}
        )
        for code in ("A", "B", "C")
    }
    import_answer_keys(session, pv, keys)
    return pv


def test_a_flipped_ref_is_counted_once_not_once_per_variant(session, app):
    slug = f"flip-{secrets.token_hex(3)}"
    _import_with_variants(session, slug, 1, triage_value=True)
    _import_with_variants(session, slug, 2, triage_value=False)
    session.commit()

    result = app.test_cli_runner().invoke(
        args=["packs", "diff", "--company", slug, "--from", "1", "--to", "2"]
    )

    assert result.exit_code == 0, result.output
    # INV-1 flips in all three variants (A, B, C), which is three IdentityChange rows for one
    # ref. The summary must say one ref, not three -- that threefold overstatement (C1) is
    # exactly what a reader skims before deciding whether to migrate students.
    assert "1 ref(s) changed meaning, 1 of them flipping a triage answer" in result.output


def test_the_command_issues_only_reads(session, app):
    """`flask packs diff` is meant to be run against the live database holding students' real
    work, before anyone is migrated -- its only safety property is that it cannot write. This
    listens on the same connection the CLI invocation is routed onto (by the autouse fixture
    above) and records every statement's first word, so a future edit that adds so much as a
    flush cannot pass silently."""
    slug = f"ro-{secrets.token_hex(3)}"

    # Listen from before any setup query runs, not just around invoke(): the session's own
    # lazy autobegin opens its first SAVEPOINT (join_transaction_mode="create_savepoint", the
    # mechanism this whole harness relies on for isolation) the moment something is first asked
    # of the connection -- and if that happens to be triggered by *our* explicit
    # `session.connection()` call after setup rather than by setup's own first query, the
    # SAVEPOINT's lazy emission lands inside the capture window instead of outside it, as an
    # artefact of this test's bookkeeping rather than anything `packs diff` did. Listening from
    # the start and only judging the statements issued *during* `invoke()` sidesteps that: the
    # fixture's own transaction is already open by then, so nothing is left for the CLI's fresh
    # session to open.
    statements: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.strip().split(None, 1)[0].upper())

    connection = session.connection()
    event.listen(connection, "before_cursor_execute", _record)
    try:
        _import(session, slug, 1)
        _import(session, slug, 2, rename=("INV-1", "A different artefact"))
        session.commit()

        statements.clear()  # only judge what `invoke()` itself issues, not this test's setup
        result = app.test_cli_runner().invoke(
            args=["packs", "diff", "--company", slug, "--from", "1", "--to", "2"]
        )
    finally:
        event.remove(connection, "before_cursor_execute", _record)

    assert result.exit_code == 0, result.output
    assert statements, "expected the command to issue at least one statement"
    forbidden = {"INSERT", "UPDATE", "DELETE", "COMMIT", "SAVEPOINT"}
    assert not (set(statements) & forbidden), statements
    assert all(kind == "SELECT" for kind in statements), statements
