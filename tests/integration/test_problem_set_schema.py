"""The shape a chapter problem set needs, before anything uses it.

A problem set is a small pack, so almost nothing new is required -- but what is new has to be
right first: a `kind` that defaults to the practice sets that already exist, a per-problem attempt
row that cannot be duplicated, and somewhere for a problem's prose to live. Each of those is a
place a later task would otherwise discover the gap by failing obscurely.
"""

from __future__ import annotations

from datetime import date

import pytest
from originalentry.extensions import db
from originalentry.models import (
    KIND_PRACTICE_SET,
    KIND_PROBLEM_SET,
    PACK_KINDS,
    Assignment,
    ContentPack,
    PackVersion,
    ProblemAttempt,
    Section,
    User,
    Variant,
    Workspace,
)
from originalentry.packs import schema
from originalentry.packs.importer import import_answer_keys, import_content
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from tests.packs import testco_alpha

pytestmark = pytest.mark.db


@pytest.fixture
def workspace(session):
    """The smallest workspace a ProblemAttempt can point at."""
    pv = import_content(session, schema.load_pack(testco_alpha.PACK),
                        source_sha256="pss" + "0" * 61)
    import_answer_keys(session, pv, {"A": schema.load_answer_key(testco_alpha.KEY_A)})
    variant_id = session.scalars(select(Variant.id).where(Variant.pack_version_id == pv.id)).first()
    section = Section(name="Sec", join_code="pss-join")
    student = User(email="pss@example.edu", given_name="Ada", family_name="Sowande")
    session.add_all([section, student])
    session.flush()
    assignment = Assignment(section_id=section.id, title="Chapter 3", company_policy="fixed",
                            fixed_pack_version_id=pv.id)
    session.add(assignment)
    session.flush()
    ws = Workspace(assignment_id=assignment.id, student_id=student.id, pack_version_id=pv.id,
                   variant_id=variant_id, status="in_progress")
    session.add(ws)
    session.flush()
    return ws


def test_no_pack_anywhere_carries_an_unknown_kind(session, workspace):
    """The backfill and the default together: every row the migration touched became a practice
    set, and nothing since has invented a third kind.

    The `workspace` fixture is taken so this cannot pass on an empty table -- the development
    branch holds no packs of its own, and a set comparison against nothing proves nothing.
    """
    kinds = set(session.scalars(db.select(ContentPack.kind)).all())

    assert kinds, "no packs at all: this test would pass vacuously"
    assert kinds <= set(PACK_KINDS), f"unknown kinds: {sorted(kinds - set(PACK_KINDS))}"
    assert session.scalars(db.select(ContentPack).filter_by(kind=None)).first() is None


def test_a_pack_imported_the_ordinary_way_is_a_practice_set(session, workspace):
    """The default is what protects every existing importer: `import_content` never passes a kind,
    so a pack imported by the practice-set path must not land as a problem set."""
    version = session.get(PackVersion, workspace.pack_version_id)
    pack = session.get(ContentPack, version.content_pack_id)

    assert pack.kind == KIND_PRACTICE_SET


def test_an_attempt_row_is_unique_per_workspace_and_problem(session, workspace):
    """Two rows for one problem would make the attempt count depend on which was read first."""
    session.add(ProblemAttempt(workspace_id=workspace.id, document_ref="P3-02", attempts=1))
    session.flush()
    session.add(ProblemAttempt(workspace_id=workspace.id, document_ref="P3-02", attempts=3))

    with pytest.raises(IntegrityError):
        session.flush()


def test_two_problems_in_one_workspace_are_fine(session, workspace):
    """Guards the guard above: the constraint must be on the pair, not on the workspace."""
    session.add(ProblemAttempt(workspace_id=workspace.id, document_ref="P3-01", attempts=1))
    session.add(ProblemAttempt(workspace_id=workspace.id, document_ref="P3-02", attempts=1))
    session.flush()

    rows = session.scalars(
        db.select(ProblemAttempt).filter_by(workspace_id=workspace.id)).all()
    assert len(rows) == 2


def test_an_attempt_starts_at_zero_and_unrevealed(session, workspace):
    """A row may exist before the first successful submission -- a refused one creates nothing,
    but a reveal can come first -- so the defaults must mean "nothing has counted yet"."""
    attempt = ProblemAttempt(workspace_id=workspace.id, document_ref="P3-03")
    session.add(attempt)
    session.flush()

    assert attempt.attempts == 0
    assert attempt.answer_shown_at is None
    assert attempt.last_submitted_at is None


def test_an_assignment_carries_how_many_problems_count(session, workspace):
    """Null for every practice set, which is why it cannot be NOT NULL."""
    assignment = session.get(Assignment, workspace.assignment_id)

    assert assignment.problems_required is None

    assignment.problems_required = 6
    session.flush()
    assert session.get(Assignment, assignment.id).problems_required == 6


def test_a_pack_carries_its_textbook_and_chapter(session):
    """What the chapter picker lists and what Block A names. Null for a practice set."""
    pack = ContentPack(slug="openstax-fa-ch3", company_name="Chapter 3 problems",
                       kind=KIND_PROBLEM_SET, textbook="OpenStax Financial Accounting",
                       chapter_label="Chapter 3", chapter_ordinal=3)
    session.add(pack)
    session.flush()

    stored = session.get(ContentPack, pack.id)
    assert (stored.kind, stored.textbook, stored.chapter_label, stored.chapter_ordinal) == (
        KIND_PROBLEM_SET, "OpenStax Financial Accounting", "Chapter 3", 3)


def test_a_document_can_carry_a_problem_stem():
    """schema.Document had nowhere for prose: guidance is capped at two documents per pack by
    validate._v10_guided, so it cannot hold ten stems."""
    document = schema.Document(ref="P3-02", display_ref="P3-02", type="problem",
                               date=date(2026, 10, 5), received_seq=1, stem="On 5 October...")

    assert document.stem.startswith("On 5 October")


def test_a_document_without_a_stem_is_still_valid():
    """Every existing pack's documents have no stem, and they must keep importing."""
    document = schema.Document(ref="D-01", display_ref="D-01", type="sales_invoice",
                               date=date(2026, 10, 5), received_seq=1)

    assert document.stem is None


def test_a_company_can_carry_its_textbook_and_chapter():
    """The pack source is where the importer reads the chapter metadata from."""
    company = schema.Company(slug="openstax-fa-ch3", name="Chapter 3 problems",
                             accent_hex="#334155", monogram="C3",
                             textbook="OpenStax Financial Accounting",
                             chapter_label="Chapter 3", chapter_ordinal=3)

    assert (company.textbook, company.chapter_label, company.chapter_ordinal) == (
        "OpenStax Financial Accounting", "Chapter 3", 3)


def test_the_pack_schema_still_forbids_an_unknown_field():
    """extra="forbid" is what makes a typo in a chapter file an import failure rather than a
    silently ignored line."""
    with pytest.raises(ValidationError):
        schema.Document(ref="x", display_ref="x", type="problem", date=date(2026, 1, 1),
                        received_seq=1, stemm="typo")
