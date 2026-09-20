"""Assemble a pack from an authoring source, computing the answers with the engine (T5).

The **source** is a dict shaped almost exactly like ``pack.json``, plus two author-only pieces
the generator strips or consumes:

- ``answers``: ``{variant_code: {triage, designated_journal_documents, expected_entries,
  adjustments, error_signatures}}`` — the answer, minus the computed figures.
- each checkpoint may carry a ``measure`` (``{account, stage?}``) saying which balance it tests;
  the generator computes the figure per variant.

``build`` returns a :class:`GeneratedPack` (the finished ``pack.json`` dict, one answer-key dict
per variant with ``expected_balances`` and ``checkpoints`` filled in, and any rendered images).
It raises :class:`GeneratorError` — listing every problem — if the finished pack would be refused
on upload.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field

from ..ledger import balances
from ..packs import schema
from ..packs.replay import build_replay_snapshot
from ..packs.validate import Problem, validate_pack

# A pack checkpoint's stage vocabulary → the engine's trial-balance stage.
_STAGE_FROM_CHECKPOINT = {
    "posted": "unadjusted",
    "unadjusted": "unadjusted",
    "adjusted": "adjusted",
    "closed": "post_closing",
    "post_closing": "post_closing",
}


class GeneratorError(Exception):
    """The authored pack would be refused. ``problems`` names each one with its JSON path."""

    def __init__(self, problems: list[Problem]):
        self.problems = problems
        super().__init__("; ".join(f"{p.path}: {p.message}" for p in problems))


@dataclass
class GeneratedPack:
    pack: dict
    keys: dict[str, dict] = field(default_factory=dict)
    images: dict[str, bytes] = field(default_factory=dict)  # "documents/A/INV-1.png" -> bytes


def _safe_ref(ref: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", ref)


def build(source: dict, *, render_images: bool = False) -> GeneratedPack:
    src = copy.deepcopy(source)
    answers: dict[str, dict] = src.pop("answers", {})

    # Consume author-only checkpoint measures so what's left is a clean pack.json.
    measures: dict[str, dict] = {}
    for checkpoint in src.get("checkpoints", []):
        measure = checkpoint.pop("measure", None)
        if measure:
            measures[checkpoint["key"]] = measure

    images: dict[str, bytes] = {}
    if render_images:
        _attach_images(src, images)

    # Validate the pack shape early (clear pydantic errors, not a later mystery).
    try:
        pack = schema.load_pack(src)
    except Exception as exc:  # pydantic ValidationError
        raise GeneratorError([Problem("pack", "V1", str(exc))]) from exc

    variant_codes = [v["code"] for v in src.get("variants", [])]
    keys: dict[str, dict] = {}
    for code in variant_codes:
        keys[code] = _build_key(src, pack, code, answers.get(code, {}), measures)

    # Final gate: run the same rules the upload screen runs, including V9 (replay reproduces the
    # figures we just computed — so it must pass, and a mismatch means an authoring bug).
    loaded_keys = {code: schema.load_answer_key(k) for code, k in keys.items()}
    problems = validate_pack(pack, loaded_keys)
    if problems:
        raise GeneratorError(problems)

    return GeneratedPack(pack=src, keys=keys, images=images)


def _build_key(
    src: dict, pack: schema.Pack, code: str, answer: dict, measures: dict[str, dict]
) -> dict:
    key_dict = {
        "variant": code,
        "triage": answer.get("triage", {}),
        "designated_journal_documents": answer.get("designated_journal_documents", {}),
        "expected_entries": answer.get("expected_entries", []),
        "adjustments": answer.get("adjustments", []),
        "error_signatures": answer.get("error_signatures", []),
        "expected_balances": {},
        "checkpoints": {},
    }
    snapshot = build_replay_snapshot(pack, schema.load_answer_key(key_dict))

    adjusted = balances(snapshot, "adjusted")
    post_closing = balances(snapshot, "post_closing")
    key_dict["expected_balances"] = {
        "adjusted": {n: c for n, c in sorted(adjusted.items()) if c != 0},
        "post_closing": {n: c for n, c in sorted(post_closing.items()) if c != 0},
    }

    checkpoint_values: dict[str, int] = {}
    by_stage: dict[str, dict[str, int]] = {}
    for checkpoint in src.get("checkpoints", []):
        measure = measures.get(checkpoint["key"])
        if not measure:
            continue
        stage = measure.get("stage") or _STAGE_FROM_CHECKPOINT.get(checkpoint.get("stage", ""))
        if stage is None:
            continue
        stage_balances = by_stage.setdefault(stage, balances(snapshot, stage))
        checkpoint_values[checkpoint["key"]] = stage_balances.get(measure["account"], 0)
    key_dict["checkpoints"] = checkpoint_values
    return key_dict


def _attach_images(src: dict, images: dict[str, bytes]) -> None:
    from . import render  # imported lazily so the core works without Pillow

    company = src.get("company", {})
    for document in src.get("documents", []):
        for code, variant in (document.get("variants") or {}).items():
            path = f"documents/{code}/{_safe_ref(document['ref'])}.png"
            variant["image"] = path
            if not (variant.get("alt") or "").strip():
                variant["alt"] = f"{document['display_ref']} for {company.get('name', '')}".strip()
            images[path] = render.render_document_png(document, code, company)
