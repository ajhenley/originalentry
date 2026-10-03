"""The answer key for one variant, arranged for printing (I5.3).

An instructor marking on paper needs the answers in the order they will meet them: each document
with the entry it takes (or the fact that it takes none), then the adjustments, the checkpoint
figures, and the balances the period should end on.

Answer keys are read here and in ``grading/`` and nowhere else (D6 rule 6). This module resolves
account numbers to names against the same manifest the pack was imported from, so nothing here
carries a hard-coded account (A21).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AnswerKey, PackVersion, Variant
from ..packs import schema

NO_ENTRY = "No entry"


@dataclass
class KeyLine:
    account: str
    party: str | None
    debit_cents: int
    credit_cents: int


@dataclass
class KeyDocument:
    ref: str
    display_ref: str
    date: object
    takes_entry: bool
    journal: str
    lines: list[KeyLine] = field(default_factory=list)
    #: Why this document takes no entry (V17's own field), set only where ``takes_entry`` is
    #: False. An instructor marking on paper needs the reason, not only the bare "No entry" --
    #: the same reason scripts/build_walkthrough.py already prints, now reaching the app too.
    reason: str = ""


@dataclass
class KeyAdjustment:
    label: str
    basis: str
    amount_cents: int | None
    lines: list[KeyLine] = field(default_factory=list)


@dataclass
class KeyCheckpoint:
    ordinal: int
    prompt: str
    figure_cents: int


@dataclass
class PrintableKey:
    variant: str
    company_name: str
    documents: list[KeyDocument] = field(default_factory=list)
    adjustments: list[KeyAdjustment] = field(default_factory=list)
    checkpoints: list[KeyCheckpoint] = field(default_factory=list)
    closing_balances: list[tuple[str, int]] = field(default_factory=list)


def _account_labels(manifest: dict) -> dict[str, str]:
    return {a["number"]: f"{a['number']} {a['name']}" for a in manifest.get("accounts", [])}


def _party_labels(manifest: dict) -> dict[str, str]:
    return {p["code"]: p["name"] for p in manifest.get("parties", [])}


def _journal_labels(manifest: dict) -> dict[str, str]:
    return {j["key"]: j["name"] for j in manifest.get("journals", [])}


def _lines(key_lines, accounts: dict[str, str], parties: dict[str, str]) -> list[KeyLine]:
    return [
        KeyLine(
            account=accounts.get(line.account, line.account),
            party=parties.get(line.party) if line.party else None,
            debit_cents=line.debit or 0,
            credit_cents=line.credit or 0,
        )
        for line in key_lines
    ]


def load_key(session: Session, pack_version: PackVersion, variant_code: str) -> AnswerKey | None:
    variant_id = session.scalars(
        select(Variant.id).where(
            Variant.pack_version_id == pack_version.id, Variant.code == variant_code
        )
    ).one_or_none()
    if variant_id is None:
        return None
    return session.scalars(
        select(AnswerKey).where(
            AnswerKey.pack_version_id == pack_version.id, AnswerKey.variant_id == variant_id
        )
    ).one_or_none()


def printable_key(
    session: Session, pack_version: PackVersion, variant_code: str, company_name: str
) -> PrintableKey | None:
    row = load_key(session, pack_version, variant_code)
    if row is None:
        return None

    key = schema.load_answer_key(row.payload)
    manifest = pack_version.manifest or {}
    accounts = _account_labels(manifest)
    parties = _party_labels(manifest)
    journals = _journal_labels(manifest)

    entry_by_document = {entry.document: entry for entry in key.expected_entries}
    documents = []
    for doc in manifest.get("documents", []):
        ref = doc["ref"]
        entry = entry_by_document.get(ref)
        # A document is in the key's triage as True when it takes an entry; anything the key does
        # not place is a document the student is meant to leave alone.
        takes_entry = bool(key.triage.get(ref, entry is not None))
        documents.append(
            KeyDocument(
                ref=ref,
                display_ref=doc.get("display_ref") or ref,
                date=doc.get("date"),
                takes_entry=takes_entry,
                journal=journals.get(entry.journal, entry.journal) if entry else NO_ENTRY,
                lines=_lines(entry.lines, accounts, parties) if entry else [],
                reason="" if takes_entry else key.triage_reasons.get(ref, ""),
            )
        )

    adjustments = [
        KeyAdjustment(
            label=adj.label,
            basis=adj.amount_basis,
            amount_cents=adj.amount,
            lines=[
                KeyLine(
                    account=accounts.get(part.account, part.account),
                    party=None,
                    debit_cents=adj.amount if part.side == "debit" and adj.amount else 0,
                    credit_cents=adj.amount if part.side == "credit" and adj.amount else 0,
                )
                for part in adj.pattern
            ],
        )
        for adj in key.adjustments
    ]

    ordinal_of = {c["key"]: c.get("ordinal") or 0 for c in manifest.get("checkpoints", [])}
    prompt_of = {c["key"]: c.get("prompt") or c["key"] for c in manifest.get("checkpoints", [])}
    checkpoints = sorted(
        (
            KeyCheckpoint(
                ordinal=ordinal_of.get(cp_key, 0),
                prompt=prompt_of.get(cp_key, cp_key),
                figure_cents=figure,
            )
            for cp_key, figure in key.checkpoints.items()
        ),
        key=lambda c: c.ordinal,
    )

    final = key.expected_balances.get("post_closing") or key.expected_balances.get("adjusted") or {}
    closing = [
        (accounts.get(number, number), cents)
        for number, cents in sorted(final.items())
    ]

    return PrintableKey(
        variant=variant_code,
        company_name=company_name,
        documents=documents,
        adjustments=adjustments,
        checkpoints=checkpoints,
        closing_balances=closing,
    )
