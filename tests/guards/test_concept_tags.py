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


def _signature_keys_on_disk() -> set[str]:
    """Every error-signature key any pack source declares, at any depth.

    Signatures live on each AnswerKey, so the same key appears once per variant; the union is what
    matters here, not where it sits.
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


def _tagged(session, kind: str) -> set[str]:
    return set(session.scalars(
        db.select(ConceptTag.artifact_key).filter_by(artifact_kind=kind)).all())


def test_the_pack_sources_declare_signatures_at_all():
    """Guards the guard: if the walk stopped finding anything, the signature test below would
    pass vacuously by comparing an empty set against an empty set."""
    assert len(_signature_keys_on_disk()) >= 13


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
    misconception the screen silently cannot name."""
    tagged = _tagged(session, "signature")
    declared = _signature_keys_on_disk()

    assert declared <= tagged, f"untagged signatures: {sorted(declared - tagged)}"


def test_concept_groups_are_only_the_two_the_model_names(session):
    """The two groups are measured differently -- marks for one, students for the other -- so a
    third would have no defined measure at all."""
    groups = set(session.scalars(db.select(Concept.group)).all())

    assert groups <= set(GROUPS), f"unexpected groups: {sorted(groups - set(GROUPS))}"
