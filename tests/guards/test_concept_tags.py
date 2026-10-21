"""Every concept tag names something real.

The tags are seeded by migration against keys that live in pack sources and in
``packs.validate.KNOWN_COMPONENTS``. Nothing at runtime would notice a tag pointing at a key that
had been renamed -- the concept would simply stop appearing, and a dashboard that quietly describes
less than it claims is the failure this guard exists to prevent.

Component tags are checked against ``KNOWN_COMPONENTS`` and signature tags against the pack sources
on disk, **not** against imported pack rubrics: four component keys appear in no pack, so a guard
written against what has been imported fails on day one while proving nothing.
"""

from __future__ import annotations

import json
import pathlib

import pytest
from originalentry.extensions import db
from originalentry.models import GROUPS, Concept, ConceptTag
from originalentry.packs.validate import KNOWN_COMPONENTS

pytestmark = pytest.mark.db

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _collect(node, key: str, out: list) -> None:
    if isinstance(node, dict):
        for name, value in node.items():
            if name == key and value:
                out.append(value)
            else:
                _collect(value, key, out)
    elif isinstance(node, list):
        for value in node:
            _collect(value, key, out)


def _seeded_signature_keys() -> set[str]:
    """Every error-signature key a hand-built pack source declares, at any depth.

    Signatures live on each AnswerKey, so the same key appears once per variant; the union is what
    matters here, not where it sits.

    These are the keys whose tags are *seeded by migration* (c3e71f0a95b4), so every one of them
    must be tagged in any database -- which is what the "is tagged" direction asserts below.
    """
    found: set[str] = set()
    for source in sorted(ROOT.glob("packs/*/source.json")):
        groups: list = []
        _collect(json.loads(source.read_text()), "error_signatures", groups)
        for group in groups:
            for signature in group:
                if isinstance(signature, dict) and signature.get("key"):
                    found.add(signature["key"])
    return found


def _chapter_signature_keys() -> set[str]:
    """Every error-signature key a committed chapter file declares.

    A chapter's tags are written by ``problems.importing.import_chapter``, not seeded by a
    migration, so a chapter that is committed but not yet imported legitimately has none. That is
    why these count as *declared* -- a tag naming one is naming something real -- but are not
    required to be tagged. ``tests/guards/test_chapter_files.py`` checks what can be guaranteed
    from disk; ``test_chapter_import.py`` checks that importing really writes the tags.
    """
    from originalentry.problems import chapter

    found: set[str] = set()
    for path in sorted(ROOT.glob("packs/chapters/*.yaml")):
        for problem in chapter.parse(path.read_text(encoding="utf-8")).problems:
            found.update(signature.key for signature in problem.signatures)
    return found


def _signature_keys_on_disk() -> set[str]:
    """Every signature key any committed content declares, from either authoring path."""
    return _seeded_signature_keys() | _chapter_signature_keys()


def _tagged(session, kind: str) -> set[str]:
    return set(session.scalars(
        db.select(ConceptTag.artifact_key).filter_by(artifact_kind=kind)).all())


def test_the_pack_sources_declare_signatures_at_all():
    """Guards the guard: if either walk stopped finding anything, the signature tests below would
    pass vacuously by comparing an empty set against an empty set."""
    assert len(_seeded_signature_keys()) >= 13
    assert _chapter_signature_keys(), "no chapter file declares a signature"


def test_every_component_tag_names_a_real_component(session):
    """A renamed component key must fail here, not quietly untag itself."""
    keys = _tagged(session, "component")

    assert keys <= KNOWN_COMPONENTS, f"tags naming no component: {sorted(keys - KNOWN_COMPONENTS)}"


def test_every_signature_tag_names_a_signature_some_pack_declares(session):
    declared = _signature_keys_on_disk()
    keys = _tagged(session, "signature")

    assert keys <= declared, f"tags naming no signature: {sorted(keys - declared)}"


def test_every_tag_resolves_to_a_concept(session):
    orphans = session.scalars(
        db.select(ConceptTag).outerjoin(Concept, ConceptTag.concept_id == Concept.id)
        .where(Concept.id.is_(None))).all()

    assert not orphans, f"tags with no concept: {[t.artifact_key for t in orphans]}"


def test_every_component_key_is_tagged(session):
    """"Untagged" is a transitional row on the screen, not a permanent home for a known key."""
    tagged = _tagged(session, "component")

    assert KNOWN_COMPONENTS <= tagged, f"untagged: {sorted(KNOWN_COMPONENTS - tagged)}"


def test_every_signature_any_pack_declares_is_tagged(session):
    """A signature with no concept is dropped from the mistakes block, so an untagged one is a
    misconception the screen silently cannot name.

    Hand-built packs only: their tags are seeded by migration, so this must hold in every
    database. A chapter's tags arrive with the import, which may not have happened here.
    """
    tagged = _tagged(session, "signature")
    seeded = _seeded_signature_keys()

    assert seeded <= tagged, f"untagged signatures: {sorted(seeded - tagged)}"


def test_concept_groups_are_only_the_two_the_model_names(session):
    """The two groups are measured differently -- marks for one, students for the other -- so a
    third would have no defined measure at all."""
    groups = set(session.scalars(db.select(Concept.group)).all())

    assert groups <= set(GROUPS), f"unexpected groups: {sorted(groups - set(GROUPS))}"
