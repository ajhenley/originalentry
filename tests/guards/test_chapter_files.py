"""Every chapter file committed under packs/ is one that will import.

A chapter file is content, like a pack source, and the same thing is true of both: a committed one
that cannot be imported is a trap for whoever tries next, and they will assume the importer is
broken rather than the file.

**Why this is not an extension of test_concept_tags.py.** That guard checks every signature a
committed pack declares against the tags in the *database*, and for hand-built packs those tags
are seeded by migration (c3e71f0a95b4). A chapter's tags are not: the importer writes them when
the chapter is imported. So a chapter file that is committed but not yet imported legitimately has
no tags, and folding chapter files into that guard would either fail on a fresh database or oblige
a migration per chapter -- which would undo the point of "one file, one command". What *can* be
guaranteed from disk is checked here; that the importer really writes the tags is
tests/integration/test_chapter_import.py::test_each_declared_signature_gets_a_concept_tag.
"""

from __future__ import annotations

import pathlib

import pytest
from originalentry.extensions import db
from originalentry.models import Concept
from originalentry.packs import schema, validate
from originalentry.problems import chapter

pytestmark = pytest.mark.db

ROOT = pathlib.Path(__file__).resolve().parents[2]
CHAPTERS = sorted(ROOT.glob("packs/chapters/*.yaml"))


def test_there_are_chapter_files_to_check():
    """Guards the guard: a glob that stopped matching would make every test below vacuous."""
    assert CHAPTERS, "no chapter files found under packs/chapters/"


@pytest.mark.parametrize("path", CHAPTERS, ids=lambda p: p.name)
def test_the_chapter_file_parses(path):
    chapter.parse(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", CHAPTERS, ids=lambda p: p.name)
def test_the_chapter_translates_to_a_pack_every_validator_accepts(path):
    """The real gate. V5 wants the role accounts, V10 a triage value per document, V11 a signature
    the key does not itself trigger, V15 a known rubric component -- and a chapter file that fails
    any of them fails at import, not here, where nobody is looking."""
    parsed = chapter.parse(path.read_text(encoding="utf-8"))

    pack_source, key_source = chapter.to_pack_source(parsed, version=1)
    problems = validate.validate_pack(schema.load_pack(pack_source),
                                      {chapter.VARIANT: schema.load_answer_key(key_source)})

    assert problems == [], f"{path.name}: {[f'[{p.rule}] {p.path}: {p.message}' for p in problems]}"


@pytest.mark.parametrize("path", CHAPTERS, ids=lambda p: p.name)
def test_every_concept_the_chapter_names_is_one_this_installation_has(session, path):
    """The one check the file itself cannot make: a concept is a row. An unknown one is refused at
    import, and a committed chapter that would be refused is a committed chapter nobody can use."""
    parsed = chapter.parse(path.read_text(encoding="utf-8"))
    live = set(session.scalars(db.select(Concept.key).where(Concept.retired_at.is_(None))).all())

    assert parsed.concepts <= live, f"{path.name}: unknown {sorted(parsed.concepts - live)}"


@pytest.mark.parametrize("path", CHAPTERS, ids=lambda p: p.name)
def test_every_signature_in_the_chapter_has_a_concept_to_be_tagged_with(path):
    """A signature is tagged with its own problem's concept, so a problem carrying signatures and
    no concept would leave them untagged -- a misconception the mistakes block cannot name."""
    parsed = chapter.parse(path.read_text(encoding="utf-8"))

    for problem in parsed.problems:
        if problem.signatures:
            assert problem.concept, f"{path.name}: {problem.ref} has signatures and no concept"


def test_no_two_chapters_claim_the_same_slug():
    """The slug is the pack's identity: two chapters sharing one would version over each other."""
    slugs: dict[str, str] = {}
    for path in CHAPTERS:
        slug = chapter.parse(path.read_text(encoding="utf-8")).slug
        assert slug not in slugs, f"{path.name} and {slugs[slug]} both claim {slug!r}"
        slugs[slug] = path.name


def test_no_two_chapters_declare_the_same_signature_key():
    """Signature tags are keyed by the signature key alone, so two chapters using one key would
    tag it with whichever concept was imported first and silently mislabel the other."""
    seen: dict[str, str] = {}
    for path in CHAPTERS:
        for problem in chapter.parse(path.read_text(encoding="utf-8")).problems:
            for signature in problem.signatures:
                assert signature.key not in seen, (
                    f"{path.name} and {seen[signature.key]} both declare "
                    f"signature {signature.key!r}"
                )
                seen[signature.key] = path.name
