"""`flask packs migrate`'s CLI surface (F5/T2a), deferred twice and now blocking: nothing
exercised the command itself -- not `--apply`, not `--accept-identity-changes`, not the refusal
messages this branch rewrote, not the echo-loop placement an earlier round moved out of the
`if not feasible:` branch precisely so the "accepted" lines would print on a dry run too.

Shaped like tests/integration/test_packs_diff_cli.py, which is this app-context fixture's first
caller (now in tests/integration/conftest.py); this is the second.
"""

from __future__ import annotations

import copy
import secrets
from datetime import date

import pytest
from originalentry.extensions import db
from originalentry.models import (
    Account,
    EntryLine,
    JournalEntry,
    Section,
    SourceDocument,
    User,
)
from originalentry.packs import schema
from originalentry.packs.importer import import_content
from originalentry.services.assignments import create_assignment, open_workspace
from sqlalchemy import select

from tests.packs import testco_alpha

pytestmark = pytest.mark.db

#: The account the student's entry in `_setup` credits, and what a test drops to construct a
#: migration with missing content (as opposed to merely changed identity).
USED_ACCOUNT_NUMBER = "401"


def _import(session, slug, version, rename=None, drop=None):
    data = copy.deepcopy(testco_alpha.PACK)
    data["company"]["slug"] = slug
    data["company"]["name"] = slug
    data["version"] = version
    if drop:
        data["accounts"] = [a for a in data["accounts"] if a["number"] != drop]
    if rename:
        ref, display_ref = rename
        for document in data["documents"]:
            if document["ref"] == ref:
                document["display_ref"] = display_ref
    return import_content(session, schema.load_pack(data), source_sha256=secrets.token_hex(32))


def _setup(session, slug):
    """A fixed-company assignment, one workspace, one posted entry against a document the
    student actually used -- the shape every test below needs a used ref to work with."""
    pv1 = _import(session, slug, 1)
    section = Section(name=slug, join_code=f"M{secrets.token_hex(3).upper()}")
    student = User(email=f"m-{secrets.token_hex(3)}@example.edu", role="student")
    session.add_all([section, student])
    session.flush()
    assignment = create_assignment(session, section=section, title="Dec", pack_version=pv1)
    ws = open_workspace(session, assignment, student)
    accts = {
        a.number: a.id
        for a in session.scalars(select(Account).where(Account.pack_version_id == pv1.id))
    }
    used_ref = "INV-1"
    document_id = session.scalars(
        select(SourceDocument.id).where(SourceDocument.pack_version_id == pv1.id,
                                        SourceDocument.ref == used_ref)
    ).one()
    entry = JournalEntry(workspace_id=ws.id, pack_version_id=pv1.id, journal_key="general",
                         entry_date=date(2026, 12, 2), kind="regular", client_key="m1",
                         document_id=document_id)
    session.add(entry)
    session.flush()
    session.add_all([
        EntryLine(entry_id=entry.id, workspace_id=ws.id, pack_version_id=pv1.id, line_no=1,
                  account_id=accts["112"], debit_cents=10000, credit_cents=0),
        EntryLine(entry_id=entry.id, workspace_id=ws.id, pack_version_id=pv1.id, line_no=2,
                  account_id=accts[USED_ACCOUNT_NUMBER], debit_cents=0, credit_cents=10000),
    ])
    session.flush()
    return assignment, ws, used_ref


def _invoke(app, assignment, *extra_args):
    """Unlike `flask packs diff`, `packs migrate` always ends its own `db.session` with a real
    `commit()` or `rollback()` (apply, or dry-run/refusal). The shared
    `_cli_shares_the_session_connection` fixture only re-points *which connection* a freshly
    created session binds to; it does not change *how* that session joins the transaction already
    open on it. Left at the session factory's default, a plain `Session(bind=connection)` bound
    to a connection that already has `_cli_shares_the_session_connection`'s outer transaction in
    progress treats that transaction as its own to manage directly, so the CLI's commit/rollback
    lands on the *test's* transaction, not a nested one -- confirmed by running it: a dry run (or
    even an infeasible one) wiped out every row this test had set up and committed before the
    invoke, because `packs migrate`'s dry-run path ends in `db.session.rollback()`.

    `flask packs diff` never hit this because it never commits or rolls back at all. So this is
    local to the one command here that writes, rather than folded into the shared fixture and
    risking the read-only command picking up a SAVEPOINT it would then (correctly) flag as
    unexpected -- `test_the_command_issues_only_reads` forbids one unconditionally.
    """
    session_factory = db.session.session_factory
    original = dict(session_factory.kw)
    session_factory.kw["join_transaction_mode"] = "create_savepoint"
    try:
        return app.test_cli_runner().invoke(
            args=["packs", "migrate", "--assignment", assignment.public_id,
                  "--to-version", "2", *extra_args]
        )
    finally:
        session_factory.kw.clear()
        session_factory.kw.update(original)


def test_a_dry_run_reports_and_writes_nothing(session, app):
    slug = f"migcli-{secrets.token_hex(3)}"
    assignment, ws, _ = _setup(session, slug)
    pv1_id = assignment.fixed_pack_version_id
    _import(session, slug, 2)
    session.commit()

    result = _invoke(app, assignment)

    assert result.exit_code == 0, result.output
    assert "1 workspace(s), 2 line(s)" in result.output
    assert "Dry run only" in result.output
    session.refresh(assignment)
    session.refresh(ws)
    assert assignment.fixed_pack_version_id == pv1_id
    assert ws.pack_version_id == pv1_id


def test_apply_without_the_override_refuses_and_names_the_ref(session, app):
    slug = f"migcli-{secrets.token_hex(3)}"
    assignment, ws, used_ref = _setup(session, slug)
    _import(session, slug, 2, rename=(used_ref, "Something else entirely"))
    session.commit()

    result = _invoke(app, assignment, "--apply")

    assert result.exit_code != 0
    assert used_ref in result.output
    assert "now name different documents" in result.output
    assert "accept-identity-changes" in result.output
    session.refresh(assignment)
    assert assignment.fixed_pack_version_id != _pack_version_for(session, slug, 2).id


def test_apply_with_the_override_proceeds_and_prints_the_accepted_lines(session, app):
    slug = f"migcli-{secrets.token_hex(3)}"
    assignment, ws, used_ref = _setup(session, slug)
    _import(session, slug, 2, rename=(used_ref, "Something else entirely"))
    session.commit()

    result = _invoke(app, assignment, "--apply", "--accept-identity-changes")

    assert result.exit_code == 0, result.output
    assert f"accepted: {used_ref} display_ref: Invoice 1 -> Something else entirely" \
        in result.output
    assert "Migrated." in result.output
    session.refresh(assignment)
    session.refresh(ws)
    pv2 = _pack_version_for(session, slug, 2)
    assert assignment.fixed_pack_version_id == pv2.id
    assert ws.pack_version_id == pv2.id


def test_the_refusal_names_missing_content_as_gone(session, app):
    """"gone" is the word the house style uses for content that disappeared -- it must not
    appear when nothing has, which is what the identity-only refusal test above checks."""
    slug = f"migcli-{secrets.token_hex(3)}"
    assignment, ws, _ = _setup(session, slug)
    _import(session, slug, 2, drop=USED_ACCOUNT_NUMBER)
    session.commit()

    result = _invoke(app, assignment, "--apply")

    assert result.exit_code != 0
    assert "gone" in result.output
    assert USED_ACCOUNT_NUMBER in result.output


def test_the_identity_only_refusal_never_says_gone(session, app):
    slug = f"migcli-{secrets.token_hex(3)}"
    assignment, ws, used_ref = _setup(session, slug)
    _import(session, slug, 2, rename=(used_ref, "Something else entirely"))
    session.commit()

    result = _invoke(app, assignment, "--apply")

    assert result.exit_code != 0
    assert "gone" not in result.output


def test_the_override_still_refuses_when_content_is_also_gone(session, app):
    """Pins the compound case at the CLI: accepting the identity change must not also excuse
    content that disappeared, and the identity sentence must still drop out of the message
    since an *accepted* identity change is not why this migration blocks."""
    slug = f"migcli-{secrets.token_hex(3)}"
    assignment, ws, used_ref = _setup(session, slug)
    _import(session, slug, 2, rename=(used_ref, "Something else entirely"),
           drop=USED_ACCOUNT_NUMBER)
    session.commit()

    result = _invoke(app, assignment, "--apply", "--accept-identity-changes")

    assert result.exit_code != 0
    assert "gone" in result.output
    assert "now name different documents" not in result.output
    assert f"accepted: {used_ref}" in result.output


def _pack_version_for(session, slug, version):
    from originalentry.models import ContentPack, PackVersion
    pack = session.scalars(select(ContentPack).where(ContentPack.slug == slug)).one()
    return session.scalars(
        select(PackVersion).where(PackVersion.content_pack_id == pack.id,
                                  PackVersion.version == version)
    ).one()
