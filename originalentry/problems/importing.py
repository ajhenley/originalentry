"""Importing a chapter: everything about it that is a fact about the catalogue, not the file.

``chapter.py`` is pure, so it cannot know whether a ``concept`` names a live row or what version
number is still free. Both live here, and both are checked *before* ``import_pack_zip`` runs, so a
refusal never leaves a half-imported pack behind.

One importer, not two: a chapter is translated to a pack source and goes through the same
``import_pack_zip`` path as every hand-built pack, which is what makes every validator apply to it.
"""

from __future__ import annotations

import hashlib

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    KIND_PROBLEM_SET,
    KIND_SIGNATURE,
    Concept,
    ConceptTag,
    ContentPack,
    PackVersion,
)
from ..packs.importing import import_pack_zip
from . import chapter


class ChapterImportRefused(Exception):
    """Faults only the database could find. Shaped like ``ChapterRefused`` so one caller -- the
    CLI -- can print either the same way."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = tuple(problems)
        super().__init__(f"{len(self.problems)} problem(s): " + "; ".join(self.problems))


def next_version(session: Session, slug: str) -> int:
    """The lowest version this slug does not have.

    ``_v14_catalogue`` refuses a version that does not advance, so a correction is always a new
    version -- which is also what keeps an assignment pinned to the old one working.
    """
    content_pack = session.scalars(
        select(ContentPack).where(ContentPack.slug == slug)).one_or_none()
    if content_pack is None:
        return 1
    highest = session.execute(
        select(func.max(PackVersion.version)).where(
            PackVersion.content_pack_id == content_pack.id)
    ).scalar_one()
    return 1 if highest is None else highest + 1


def import_chapter(session: Session, text: str, actor=None) -> PackVersion:
    """Import one chapter file. Raises ``chapter.ChapterRefused``, ``ChapterImportRefused`` or
    ``packs.importing.PackImportRefused``, in that order of cheapness."""
    parsed = chapter.parse(text)

    live = set(session.scalars(
        select(Concept.key).where(Concept.retired_at.is_(None))).all())
    unknown = sorted(parsed.concepts - live)
    if unknown:
        raise ChapterImportRefused([
            f"concept {name!r} is not one this installation knows. The vocabulary is fixed; "
            f"pick the closest of: {', '.join(sorted(live))}."
            for name in unknown
        ])

    _refuse_a_slug_held_by_another_kind(session, parsed)
    _refuse_an_unchanged_chapter(session, parsed)

    pack_source, key_source = chapter.to_pack_source(
        parsed, version=next_version(session, parsed.slug))
    version = import_pack_zip(
        session, chapter.to_zip(pack_source, {chapter.VARIANT: key_source}), actor=actor)

    _mark_as_a_problem_set(session, version, parsed)
    _tag_signatures(session, parsed, live_concepts=_concept_ids(session))
    session.flush()
    return version


def _refuse_a_slug_held_by_another_kind(session: Session, parsed: chapter.Chapter) -> None:
    """Refuse a chapter whose slug already belongs to a practice set.

    ``import_content`` reuses the ``ContentPack`` it finds by slug, and ``_mark_as_a_problem_set``
    then sets ``kind`` on that shared row -- so importing a chapter over a practice set's slug
    flipped that pack's kind, and ``decorators._fence`` immediately 404s Documents, Journals,
    Ledgers, Statements, the trial balance, Checkpoints and the print record for every live
    workspace pinned to any version of it. Mid-term, for a whole cohort, from one import.

    A chapter reusing its *own* slug is the ordinary versioning path and stays allowed.
    """
    existing = session.scalars(
        select(ContentPack).where(ContentPack.slug == parsed.slug)).one_or_none()
    if existing is None or existing.kind == KIND_PROBLEM_SET:
        return
    raise ChapterImportRefused([
        f"{parsed.slug!r} is already the slug of {existing.company_name!r}, which is a "
        f"{existing.kind.replace('_', ' ')}. Importing over it would change that pack's kind and "
        f"close the journals and ledgers of every student still working in it. Give this chapter "
        f"a different slug."
    ])


def _refuse_an_unchanged_chapter(session: Session, parsed: chapter.Chapter) -> None:
    """Refuse a re-import of a chapter nothing has changed in.

    ``_v14_catalogue`` refuses a repeat ``source_sha256``, which is what normally stops the same
    content being imported twice -- but the version auto-increments here, and a different version
    number is different bytes, so that check would never fire. Without this, every re-run of the
    command adds an identical version to the catalogue and the chapter picker offers a "newer"
    pack that differs in nothing.

    Checked by building the source at the version that already exists and comparing the archive's
    digest, which covers the answer key as well as the pack -- changing a figure changes only the
    key. ``chapter.to_zip`` is deterministic, which is what makes the comparison exact.
    """
    latest = session.scalars(
        select(PackVersion)
        .join(ContentPack, ContentPack.id == PackVersion.content_pack_id)
        .where(ContentPack.slug == parsed.slug)
        .order_by(PackVersion.version.desc())
        .limit(1)
    ).first()
    if latest is None:
        return

    same_pack, same_key = chapter.to_pack_source(parsed, version=latest.version)
    digest = hashlib.sha256(
        chapter.to_zip(same_pack, {chapter.VARIANT: same_key}).getvalue()).hexdigest()
    if digest == latest.source_sha256:
        raise ChapterImportRefused([
            f"{parsed.slug} is already in the catalogue at version {latest.version} and nothing "
            f"in this file has changed. A correction is a new version; an identical re-import is "
            f"not."
        ])


def _mark_as_a_problem_set(session: Session, version: PackVersion, parsed: chapter.Chapter) -> None:
    """``import_content`` is the practice-set path and knows nothing about chapters, so the kind
    and the chapter metadata are set here rather than threaded through it."""
    content_pack = session.get(ContentPack, version.content_pack_id)
    content_pack.kind = KIND_PROBLEM_SET
    content_pack.textbook = parsed.textbook
    content_pack.chapter_label = parsed.chapter_label
    content_pack.chapter_ordinal = parsed.chapter


def _concept_ids(session: Session) -> dict[str, int]:
    return {
        key: concept_id
        for key, concept_id in session.execute(
            select(Concept.key, Concept.id).where(Concept.retired_at.is_(None))).all()
    }


def _tag_signatures(
    session: Session, parsed: chapter.Chapter, *, live_concepts: dict[str, int]
) -> None:
    """One tag per signature, defaulting to its own problem's concept.

    A ``ConceptTag`` is keyed by component or signature key, and a chapter pack has exactly one
    component -- so a per-component concept could not tell two misconceptions apart. Tagging the
    signatures is what lets the mistakes block name them.

    Idempotent: a chapter re-imported as a new version declares the same signature keys, and a
    second tag for one key would make the mistakes block count a misconception twice.
    """
    already = set(session.scalars(
        select(ConceptTag.artifact_key).where(ConceptTag.artifact_kind == KIND_SIGNATURE)).all())

    for problem in parsed.problems:
        for signature in problem.signatures:
            if signature.key in already:
                continue
            already.add(signature.key)
            session.add(ConceptTag(
                concept_id=live_concepts[problem.concept],
                artifact_kind=KIND_SIGNATURE,
                artifact_key=signature.key,
            ))
