"""Pydantic schema for ``pack.json`` and answer keys (T5.2, T5.3).

This is the single source of truth for the pack format. The offline generator imports it, so
the generator and the app can never disagree about the format (T5). Money fields are integer
cents (D6 rule 1). ``extra="forbid"`` turns a stray or misspelled key into a validation error,
which is the first half of V1.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

KNOWN_FORMAT_VERSIONS = frozenset({1})

Side = Literal["debit", "credit"]
NormalBalance = Literal["debit", "credit"]
PostsMode = Literal["total", "individual"]
JournalKind = Literal["special", "general"]
AmountBasis = Literal["independent", "dependent"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ── pack.json ───────────────────────────────────────────────────────────────────────────

class Company(_Model):
    slug: str
    name: str
    accent_hex: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    monogram: str = Field(min_length=1, max_length=3)
    course_tags: list[str] = []
    scope_tags: list[str] = []


class Period(_Model):
    start: date
    end: date
    fiscal_year_end: date


class PackAccount(_Model):
    number: str
    name: str
    type: str
    normal_balance: NormalBalance
    statement_section: str | None = None
    roles: list[str] = []
    subsidiary_kind: str | None = None
    sort_order: int = 0


class PackParty(_Model):
    code: str
    kind: str
    name: str
    address: str | None = None


class Variant(_Model):
    code: str
    label: str
    drivers: dict[str, int] = {}


class VariantOpeningBalances(_Model):
    accounts: dict[str, int] = {}
    parties: dict[str, int] = {}


class JournalColumn(_Model):
    key: str
    label: str
    side: Side
    account: str | None = None  # None for an "Other accounts" column
    subsidiary_kind: str | None = None
    posts: PostsMode


class Journal(_Model):
    key: str
    name: str
    ref_prefix: str
    kind: JournalKind
    columns: list[JournalColumn] = []


class TextAlternative(_Model):
    fields: list[list[str]] = []
    lines: list[list[str]] = []


class DocumentVariant(_Model):
    image: str | None = None
    alt: str | None = None
    text_alternative: TextAlternative | None = None


class Document(_Model):
    ref: str
    display_ref: str
    type: str
    date: date
    received_seq: int
    guided: bool = False
    guidance: str | None = None
    variants: dict[str, DocumentVariant] = {}


class Checkpoint(_Model):
    key: str
    ordinal: int
    stage: str
    prompt: str


class SubtotalType(_Model):
    key: str
    label: str


class Statement(_Model):
    type: str
    title: str
    # Which of the student's own balances the statement reads: "adjusted" or "post_closing".
    stage: str = "adjusted"
    allowed_sections: list[str]
    subtotal_types: list[SubtotalType] = []
    required_subtotals: list[str] = []


class ReferenceSection(_Model):
    key: str
    title: str
    blocks: list[dict] = []  # structured blocks; block-shape validation is a later V-rule


class RubricComponent(_Model):
    key: str
    points: int = Field(gt=0)


class Rubric(_Model):
    components: list[RubricComponent] = []


class Pack(_Model):
    format_version: int
    company: Company
    version: int
    period: Period
    statement_sections: list[str] = []
    accounts: list[PackAccount]
    parties: list[PackParty] = []
    variants: list[Variant]
    opening_balances: dict[str, VariantOpeningBalances] = {}
    journals: list[Journal] = []
    documents: list[Document] = []
    checkpoints: list[Checkpoint] = []
    statements: list[Statement] = []
    reference: list[ReferenceSection] = []
    rubric: Rubric = Rubric()


# ── answer key ──────────────────────────────────────────────────────────────────────────

class KeyLine(_Model):
    account: str
    party: str | None = None
    debit: int | None = None
    credit: int | None = None


class ExpectedEntry(_Model):
    document: str
    journal: str
    kind: str = "regular"
    lines: list[KeyLine]


class AdjustmentPattern(_Model):
    account: str
    side: Side


class Adjustment(_Model):
    key: str
    label: str
    amount_basis: AmountBasis
    amount: int | None = None
    base_account: str | None = None
    pattern: list[AdjustmentPattern]


class ErrorSignature(_Model):
    key: str
    label: str
    detect: dict  # shape depends on detect.type; checked in validate.py (V11)
    deduct_points: int | None = None


class AnswerKey(_Model):
    variant: str
    triage: dict[str, bool] = {}
    designated_journal_documents: dict[str, str] = {}
    expected_entries: list[ExpectedEntry] = []
    adjustments: list[Adjustment] = []
    expected_balances: dict[str, dict[str, int]] = {}
    checkpoints: dict[str, int] = {}
    error_signatures: list[ErrorSignature] = []


def load_pack(data: dict) -> Pack:
    return Pack.model_validate(data)


def load_answer_key(data: dict) -> AnswerKey:
    return AnswerKey.model_validate(data)
