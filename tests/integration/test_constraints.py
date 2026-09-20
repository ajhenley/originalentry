"""The constraints that are the design (D5), proven against real Postgres:

- the balance trigger rejects an unbalanced entry (A4);
- the composite foreign key rejects a line that reaches into another company's chart (A20).

Both constraints are DEFERRABLE INITIALLY DEFERRED, so each test makes *only the constraint it
is exercising* immediate (by name), leaving the others deferred.
"""

from dataclasses import dataclass
from datetime import date

import pytest
from originalentry.models import (
    Account,
    Assignment,
    ContentPack,
    EntryLine,
    JournalEntry,
    PackVersion,
    Section,
    User,
    Variant,
    Workspace,
)
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.db


@dataclass
class Seed:
    workspace: Workspace
    pack_a: PackVersion
    account_a: Account
    account_b: Account


def _pack(session, slug, sha) -> tuple[PackVersion, Account]:
    pack = ContentPack(slug=slug, company_name=slug.title())
    session.add(pack)
    session.flush()
    pv = PackVersion(
        content_pack_id=pack.id, version=1,
        period_start=date(2026, 12, 1), period_end=date(2026, 12, 31),
        fiscal_year_end=date(2026, 12, 31), accent_hex="#1F5F8B", monogram="XX",
        source_sha256=sha,
    )
    session.add(pv)
    session.flush()
    account = Account(
        pack_version_id=pv.id, number="101", name="Cash",
        account_type="asset", normal_balance="debit",
    )
    session.add(account)
    session.flush()
    return pv, account


def _seed(session) -> Seed:
    pack_a, account_a = _pack(session, "alpha", "a" * 64)
    pack_b, account_b = _pack(session, "beta", "b" * 64)
    variant = Variant(pack_version_id=pack_a.id, code="A", label="Variant A")
    session.add(variant)
    section = Section(name="Sec 1", join_code="join-xyz")
    student = User(email="s@example.edu")
    session.add_all([variant, section, student])
    session.flush()
    assignment = Assignment(
        section_id=section.id, title="December cycle",
        company_policy="fixed", fixed_pack_version_id=pack_a.id,
    )
    session.add(assignment)
    session.flush()
    workspace = Workspace(
        assignment_id=assignment.id, student_id=student.id,
        pack_version_id=pack_a.id, variant_id=variant.id, status="in_progress",
    )
    session.add(workspace)
    session.flush()
    return Seed(workspace=workspace, pack_a=pack_a, account_a=account_a, account_b=account_b)


def _new_entry(session, seed: Seed, client_key: str) -> JournalEntry:
    entry = JournalEntry(
        workspace_id=seed.workspace.id, pack_version_id=seed.pack_a.id,
        journal_key="general", entry_date=date(2026, 12, 1), kind="regular",
        client_key=client_key,
    )
    session.add(entry)
    session.flush()
    return entry


def test_balance_trigger_rejects_unbalanced_entry(session):
    seed = _seed(session)
    entry = _new_entry(session, seed, "ck-balance")
    # Make only the balance trigger immediate; leave the FKs deferred.
    session.execute(text("SET CONSTRAINTS entry_line_balanced IMMEDIATE"))
    session.add(
        EntryLine(
            entry_id=entry.id, workspace_id=seed.workspace.id, pack_version_id=seed.pack_a.id,
            line_no=1, account_id=seed.account_a.id, debit_cents=100, credit_cents=0,
        )
    )
    with pytest.raises(IntegrityError) as exc:
        session.flush()
    assert "unbalanced" in str(exc.value).lower()
    session.rollback()


def test_composite_fk_rejects_cross_company_account(session):
    seed = _seed(session)
    entry = _new_entry(session, seed, "ck-scope")
    # Make only the account scope FK immediate; leave the balance trigger deferred so the
    # single line does not trip it first.
    session.execute(text("SET CONSTRAINTS entry_line_account_scope IMMEDIATE"))
    # A line in an alpha workspace that points at a beta account: (alpha_pv, beta_account_id)
    # is not a row in `account`, so the composite FK refuses it.
    session.add(
        EntryLine(
            entry_id=entry.id, workspace_id=seed.workspace.id, pack_version_id=seed.pack_a.id,
            line_no=1, account_id=seed.account_b.id, debit_cents=100, credit_cents=0,
        )
    )
    with pytest.raises(IntegrityError) as exc:
        session.flush()
    assert "entry_line_account_scope" in str(exc.value)
    session.rollback()


def test_valid_balanced_entry_is_accepted(session):
    seed = _seed(session)
    entry = _new_entry(session, seed, "ck-valid")
    session.add_all(
        [
            EntryLine(
                entry_id=entry.id, workspace_id=seed.workspace.id,
                pack_version_id=seed.pack_a.id, line_no=1,
                account_id=seed.account_a.id, debit_cents=168000, credit_cents=0,
            ),
            EntryLine(
                entry_id=entry.id, workspace_id=seed.workspace.id,
                pack_version_id=seed.pack_a.id, line_no=2,
                account_id=seed.account_a.id, debit_cents=0, credit_cents=168000,
            ),
        ]
    )
    session.flush()
    # Deferred constraints fire at commit; force the check now without persisting.
    session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    session.rollback()
