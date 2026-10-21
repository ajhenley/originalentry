"""Importing a chapter: the pack it creates, the tags it writes, and what it refuses.

The parse and the translation are covered without a database in tests/unit/test_chapter_file.py.
What needs one is everything that is a fact about the catalogue rather than about the file: the
concept a problem names has to exist, the version has to advance past what is already imported,
and every signature has to end up with a concept tag -- which is what lets the mistakes block name
a misconception for a chapter problem instead of dropping it.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from originalentry.extensions import db
from originalentry.forms.entries import EntryCommand, LineCommand
from originalentry.grading.workspace import grade_workspace
from originalentry.models import (
    KIND_PROBLEM_SET,
    Assignment,
    ConceptTag,
    ContentPack,
    PackVersion,
    ProblemAttempt,
    Section,
    User,
    Variant,
    Workspace,
)
from originalentry.problems import chapter, importing
from originalentry.services.entries import record_entry
from sqlalchemy import select

from tests.unit.test_chapter_file import VALID

pytestmark = pytest.mark.db


@pytest.fixture
def imported(session):
    return importing.import_chapter(session, VALID)


def _pack(session, version: PackVersion) -> ContentPack:
    return session.get(ContentPack, version.content_pack_id)


# ── the pack a chapter becomes ─────────────────────────────────────────────────────────

def test_importing_a_chapter_creates_a_problem_set_pack(session, imported):
    pack = _pack(session, imported)

    assert pack.kind == KIND_PROBLEM_SET
    assert pack.textbook == "OpenStax Principles of Financial Accounting"
    assert pack.chapter_label == "Analyzing and Recording Transactions"
    assert pack.chapter_ordinal == 3
    assert pack.slug.endswith("-ch3")


def test_the_pack_holds_one_document_per_problem_with_its_stem(session, imported):
    documents = imported.manifest["documents"]

    assert [d["ref"] for d in documents] == ["P3-01", "P3-02"]
    assert documents[0]["stem"].startswith("On 5 October")


def test_the_pack_is_scored_by_the_new_component(session, imported):
    """Any existing component would divide its points across every problem."""
    assert [c["key"] for c in imported.manifest["rubric"]["components"]] == ["problems_best_n"]


# ── the concept, which only the database can check ─────────────────────────────────────

def test_a_concept_that_names_no_live_concept_is_refused(session):
    """The chapter file cannot check this -- a concept is a row. An unknown one would leave the
    problem's signatures tagged against nothing, so the mistakes block could not name them."""
    broken = VALID.replace("concept: debit_credit", "concept: vibes")

    with pytest.raises(importing.ChapterImportRefused) as refused:
        importing.import_chapter(session, broken)

    assert any("vibes" in problem for problem in refused.value.problems)


def test_nothing_is_left_behind_when_a_concept_is_refused(session):
    """The check runs before the import, so a refusal cannot leave a half-imported pack."""
    broken = VALID.replace("concept: debit_credit", "concept: vibes")

    with pytest.raises(importing.ChapterImportRefused):
        importing.import_chapter(session, broken)

    slug = chapter.parse(VALID).slug
    assert session.scalars(select(ContentPack).where(ContentPack.slug == slug)).first() is None


def test_each_declared_signature_gets_a_concept_tag(session, imported):
    """What makes the mistakes block name a concept for a chapter problem."""
    tag = session.scalars(db.select(ConceptTag).filter_by(
        artifact_kind="signature", artifact_key="supplies_not_equipment")).one()

    assert tag.concept_id is not None


def test_a_signature_is_tagged_with_its_own_problem_s_concept(session):
    """Defaulting to the problem's concept is the whole mechanism: one chapter pack has one
    component, so a per-component concept could not tell two misconceptions apart."""
    two_concepts = VALID.replace(
        """  - ref: P3-02
    date: 2026-10-08
    concept: debit_credit""",
        """  - ref: P3-02
    date: 2026-10-08
    concept: unearned_revenue""").replace(
        """    stem: On 8 October the business paid $1,200 of what it owed. Record the entry.""",
        """    stem: On 8 October the business paid $1,200 of what it owed. Record the entry.
    signatures:
      - key: paid_as_expense
        label: A payment of a debt recorded as an expense, which it is not
        detect: {type: entry_line, document: P3-02, account: "140", side: debit}""")

    importing.import_chapter(session, two_concepts)

    tags = {
        tag.artifact_key: tag.concept_id
        for tag in session.scalars(db.select(ConceptTag).where(
            ConceptTag.artifact_kind == "signature",
            ConceptTag.artifact_key.in_({"supplies_not_equipment", "paid_as_expense"}))).all()
    }
    assert set(tags) == {"supplies_not_equipment", "paid_as_expense"}
    assert tags["supplies_not_equipment"] != tags["paid_as_expense"], (
        "both signatures were tagged with the same concept, so the mistakes block cannot "
        "distinguish them"
    )


def test_reimporting_the_same_signature_does_not_duplicate_its_tag(session, imported):
    """A chapter re-imported as a new version declares the same signatures. A second tag for one
    key would make the mistakes block count a misconception twice."""
    corrected = VALID.replace("agreeing to pay the rest later.",
                              "agreeing to pay the balance later.")

    importing.import_chapter(session, corrected)

    tags = session.scalars(db.select(ConceptTag).filter_by(
        artifact_kind="signature", artifact_key="supplies_not_equipment")).all()
    assert len(tags) == 1


# ── versions and re-import ─────────────────────────────────────────────────────────────

def test_the_first_import_is_version_one(session, imported):
    assert imported.version == 1


def test_reimporting_a_corrected_chapter_makes_a_new_version(session, imported):
    """Review Focus 5. import_pack_zip refuses a repeat sha and a version that does not advance,
    so a fix is a new version -- and an assignment pinned to the old one keeps it."""
    corrected = VALID.replace("agreeing to pay the rest later.",
                              "agreeing to pay the balance later.")

    second = importing.import_chapter(session, corrected)

    assert second.version == 2
    assert second.content_pack_id == imported.content_pack_id
    assert second.id != imported.id


def test_an_assignment_pinned_to_the_old_version_keeps_it(session, imported):
    """Pack immutability, which is why a mid-term correction reaches only later sections."""
    section = Section(name="Sec", join_code="chi-join")
    session.add(section)
    session.flush()
    assignment = Assignment(section_id=section.id, title="Chapter 3", company_policy="fixed",
                            fixed_pack_version_id=imported.id, problems_required=1)
    session.add(assignment)
    session.flush()

    importing.import_chapter(session, VALID.replace("rest later.", "balance later."))

    assert session.get(Assignment, assignment.id).fixed_pack_version_id == imported.id


def test_importing_the_very_same_file_twice_is_refused(session, imported):
    """Nothing changed, so there is nothing to version.

    V14's repeat-sha check cannot catch this: the version auto-increments, and a different version
    number is different bytes. Without a check of its own, every re-run of the command would add
    an identical version and the chapter picker would offer a "newer" pack that differs in
    nothing.
    """
    with pytest.raises(importing.ChapterImportRefused) as refused:
        importing.import_chapter(session, VALID)

    assert any("nothing in this file has changed" in p for p in refused.value.problems)


def test_next_version_counts_from_the_catalogue(session, imported):
    assert importing.next_version(session, chapter.parse(VALID).slug) == 2
    assert importing.next_version(session, "a-slug-nobody-has-imported") == 1


# ── the end to end: marks follow the reveal ────────────────────────────────────────────

def test_marks_follow_the_reveal(session, imported):
    """Grade, reveal one problem, grade again: the mark falls and the evidence says why.

    The seam this proves is the whole chain -- a chapter imported from a file, graded by
    problems_best_n, with the reveal read from problem_attempt by load_work.
    """
    student = User(email="chi@example.edu", given_name="Ada", family_name="Sowande")
    section = Section(name="Sec", join_code="chi-rev")
    session.add_all([student, section])
    session.flush()
    assignment = Assignment(section_id=section.id, title="Chapter 3", company_policy="fixed",
                            fixed_pack_version_id=imported.id, problems_required=2)
    session.add(assignment)
    session.flush()
    variant_id = session.scalars(
        select(Variant.id).where(Variant.pack_version_id == imported.id)).one()
    ws = Workspace(assignment_id=assignment.id, student_id=student.id,
                   pack_version_id=imported.id, variant_id=variant_id, status="in_progress")
    session.add(ws)
    session.flush()

    record_entry(session, ws, EntryCommand(
        journal_key="general", kind="regular", document_ref="P3-01",
        entry_date=imported.period_start, description="Equipment",
        lines=[LineCommand("150", None, 480000, 0), LineCommand("101", None, 0, 180000),
               LineCommand("201", None, 0, 300000)],
        client_key="p3-01"))
    session.flush()

    before = grade_workspace(session, ws).component("problems_best_n").points
    assert before > 0, "a correct problem earned nothing, so the reveal proves nothing"

    session.add(ProblemAttempt(workspace_id=ws.id, document_ref="P3-01", attempts=1,
                              answer_shown_at=datetime.now(UTC)))
    session.flush()

    after = grade_workspace(session, ws).component("problems_best_n")

    assert after.points == 0.0
    row = next(r for r in after.evidence if r.item == "P3-01")
    assert "revealed" in row.detail.lower()


# ── the command ────────────────────────────────────────────────────────────────────────

def test_the_cli_imports_a_chapter_file(app, session, tmp_path):
    path = tmp_path / "chapter.yaml"
    path.write_text(VALID)

    result = app.test_cli_runner().invoke(args=["problems", "import", str(path)])

    assert result.exit_code == 0, result.output
    slug = chapter.parse(VALID).slug
    assert session.scalars(select(ContentPack).where(ContentPack.slug == slug)).one()


def test_the_cli_reports_every_fault_and_imports_nothing(app, session, tmp_path):
    """An author runs this command, reads its output, and fixes the file. Reporting one fault at a
    time would make a ten-problem chapter ten runs."""
    path = tmp_path / "chapter.yaml"
    path.write_text(VALID
                    .replace('{account: "201", credit: 300000}', '{account: "201", credit: 1}')
                    .replace('stem: On 8 October the business paid $1,200 of what it owed. '
                             'Record the entry.', 'stem: " "'))

    result = app.test_cli_runner().invoke(args=["problems", "import", str(path)])

    assert result.exit_code != 0
    assert "does not balance" in result.output
    assert "stem" in result.output
    slug = chapter.parse(VALID).slug
    assert session.scalars(select(ContentPack).where(ContentPack.slug == slug)).first() is None


# ── the slug is an identity, and identities collide ────────────────────────────────────

def test_a_chapter_cannot_take_over_a_practice_set_s_slug(session):
    """The most destructive thing on this feature's surface.

    `import_content` reuses the ContentPack it finds by slug, and `_mark_as_a_problem_set` then
    sets `kind` on that shared row. So a chapter whose slug matched an existing practice set
    flipped that pack's kind -- and `decorators._fence` immediately 404s Documents, Journals,
    Ledgers, Statements, the trial balance, Checkpoints and Print for every live workspace pinned
    to any version of it. Mid-term, for a whole cohort, from one import.
    """
    from originalentry.packs import schema as pack_schema
    from originalentry.packs.importer import import_answer_keys, import_content

    from tests.packs import testco_alpha

    practice = import_content(session, pack_schema.load_pack(testco_alpha.PACK),
                              source_sha256="slu" + "0" * 61)
    import_answer_keys(session, practice,
                       {"A": pack_schema.load_answer_key(testco_alpha.KEY_A)})
    practice_pack = session.get(ContentPack, practice.content_pack_id)
    assert practice_pack.kind != KIND_PROBLEM_SET

    colliding = VALID.replace("slug: openstax-fa-ch3\n", "") \
        if "slug: openstax-fa-ch3" in VALID else VALID
    colliding = colliding.replace(
        "textbook: OpenStax Principles of Financial Accounting",
        f"slug: {practice_pack.slug}\ntextbook: OpenStax Principles of Financial Accounting")

    with pytest.raises(importing.ChapterImportRefused) as refused:
        importing.import_chapter(session, colliding)

    assert practice_pack.slug in str(refused.value)
    assert session.get(ContentPack, practice.content_pack_id).kind != KIND_PROBLEM_SET


def test_a_chapter_can_still_take_its_own_slug_again(session, imported):
    """Guards the refusal from the inside: a chapter re-imported as a new version must still be
    allowed to reuse its own slug, which is the whole versioning story."""
    corrected = VALID.replace("agreeing to pay the rest later.", "agreeing to pay the balance.")

    second = importing.import_chapter(session, corrected)

    assert second.content_pack_id == imported.content_pack_id
