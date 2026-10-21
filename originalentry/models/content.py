"""Content tables (D3). Immutable at runtime; a content fix cannot corrupt a ledger (T4).

The composite unique keys — ``(pack_version_id, id)`` on account/party/document — exist so that
work rows can carry composite foreign keys and a forgotten scope fails loudly (D6 rule 5).
Journals, statements, checkpoints, reference and rubric live in ``pack_version.manifest`` (jsonb);
only the rows that work tables must point at with composite FKs are normalised into their own
tables.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, deferred, mapped_column, relationship

from ..extensions import db

# What a pack is for. A practice set is the full accounting cycle for one company; a problem set is
# a chapter of short, independent journal-entry problems. They share every content table -- the
# difference is which screens and which rubric component apply, so it is a column, not a hierarchy.
KIND_PRACTICE_SET = "practice_set"
KIND_PROBLEM_SET = "problem_set"
PACK_KINDS = (KIND_PRACTICE_SET, KIND_PROBLEM_SET)


class ContentPack(db.Model):
    __tablename__ = "content_pack"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    company_name: Mapped[str] = mapped_column(String(200))
    course_tags: Mapped[list] = mapped_column(JSONB, default=list)
    kind: Mapped[str] = mapped_column(String(20), default=KIND_PRACTICE_SET,
                                      server_default=KIND_PRACTICE_SET)
    # Chapter metadata, for a problem set only: what the chapter picker lists and what names the
    # row in the mastery view. Null for every practice set.
    textbook: Mapped[str | None] = mapped_column(String(200))
    chapter_label: Mapped[str | None] = mapped_column(String(80))
    chapter_ordinal: Mapped[int | None] = mapped_column(Integer)


class PackVersion(db.Model):
    __tablename__ = "pack_version"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    content_pack_id: Mapped[int] = mapped_column(ForeignKey("content_pack.id"))
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    fiscal_year_end: Mapped[date] = mapped_column(Date)
    accent_hex: Mapped[str] = mapped_column(String(7))
    monogram: Mapped[str] = mapped_column(String(3))
    scope_tags: Mapped[list] = mapped_column(JSONB, default=list)
    has_images: Mapped[bool] = mapped_column(Boolean, default=False)
    # journals, statements, checkpoints, reference, rubric, statement_sections, company meta.
    manifest: Mapped[dict] = mapped_column(JSONB, default=dict)
    source_sha256: Mapped[str] = mapped_column(String(64), unique=True)
    generator_version: Mapped[str] = mapped_column(String(40), default="")
    uploaded_by: Mapped[int | None] = mapped_column(BigInteger)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    first_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    content_pack: Mapped[ContentPack] = relationship()

    __table_args__ = (UniqueConstraint("content_pack_id", "version"),)


class Variant(db.Model):
    __tablename__ = "variant"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    pack_version_id: Mapped[int] = mapped_column(ForeignKey("pack_version.id"))
    code: Mapped[str] = mapped_column(String(20))
    label: Mapped[str] = mapped_column(String(120))
    driver_values: Mapped[dict] = mapped_column(JSONB, default=dict)

    __table_args__ = (
        UniqueConstraint("pack_version_id", "code"),
        UniqueConstraint("pack_version_id", "id"),  # composite-FK target
    )


class Account(db.Model):
    __tablename__ = "account"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    pack_version_id: Mapped[int] = mapped_column(ForeignKey("pack_version.id"))
    number: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(200))
    account_type: Mapped[str] = mapped_column(String(40))
    normal_balance: Mapped[str] = mapped_column(String(6))  # debit | credit
    statement_section: Mapped[str | None] = mapped_column(String(60))
    roles: Mapped[list] = mapped_column(JSONB, default=list)
    subsidiary_kind: Mapped[str | None] = mapped_column(String(40))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        UniqueConstraint("pack_version_id", "number"),
        UniqueConstraint("pack_version_id", "id"),  # composite-FK target (D5)
    )


class Party(db.Model):
    __tablename__ = "party"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    pack_version_id: Mapped[int] = mapped_column(ForeignKey("pack_version.id"))
    code: Mapped[str] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(200))
    address: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("pack_version_id", "code"),
        UniqueConstraint("pack_version_id", "id"),  # composite-FK target (D5)
    )


class SourceDocument(db.Model):
    __tablename__ = "source_document"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    pack_version_id: Mapped[int] = mapped_column(ForeignKey("pack_version.id"))
    ref: Mapped[str] = mapped_column(String(60))
    display_ref: Mapped[str] = mapped_column(String(120))
    doc_type: Mapped[str] = mapped_column(String(60))
    doc_date: Mapped[date] = mapped_column(Date)
    received_seq: Mapped[int] = mapped_column(Integer)
    guided: Mapped[bool] = mapped_column(Boolean, default=False)
    guidance: Mapped[str | None] = mapped_column(Text)
    # No requires_entry column — that is answer information and lives only in the key (tension 5).

    __table_args__ = (
        UniqueConstraint("pack_version_id", "ref"),
        UniqueConstraint("pack_version_id", "id"),  # composite-FK target (D5)
    )


class PackAsset(db.Model):
    """A file the pack brought with it — a document image (D3).

    The bytes live in Postgres rather than a bucket: there is no second service to secure, and an
    image is reachable only through a route that checks whose workspace is asking (T1.1, T11).
    """

    __tablename__ = "pack_asset"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    pack_version_id: Mapped[int] = mapped_column(ForeignKey("pack_version.id"))
    # The path as the pack names it, e.g. documents/A/INV-1.png
    path: Mapped[str] = mapped_column(String(300))
    sha256: Mapped[str] = mapped_column(String(64))
    content_type: Mapped[str] = mapped_column(String(60))
    byte_size: Mapped[int] = mapped_column(BigInteger)
    # Deferred: a ledger query must never drag image bytes along with it.
    data: Mapped[bytes] = deferred(mapped_column(LargeBinary))

    __table_args__ = (UniqueConstraint("pack_version_id", "path"),)


class AnswerKey(db.Model):
    __tablename__ = "answer_key"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    pack_version_id: Mapped[int] = mapped_column(ForeignKey("pack_version.id"))
    variant_id: Mapped[int] = mapped_column(ForeignKey("variant.id"))
    # Read only by grading/ and staff/ (D6 rule 6). Never joined into a student query.
    payload: Mapped[dict] = mapped_column(JSONB)

    __table_args__ = (UniqueConstraint("pack_version_id", "variant_id"),)


class AccountOpeningBalance(db.Model):
    __tablename__ = "account_opening_balance"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"))
    variant_id: Mapped[int] = mapped_column(ForeignKey("variant.id"))
    balance_cents: Mapped[int] = mapped_column(BigInteger)  # debit-positive (D1)

    __table_args__ = (UniqueConstraint("account_id", "variant_id"),)


class PartyOpeningBalance(db.Model):
    __tablename__ = "party_opening_balance"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    party_id: Mapped[int] = mapped_column(ForeignKey("party.id"))
    variant_id: Mapped[int] = mapped_column(ForeignKey("variant.id"))
    balance_cents: Mapped[int] = mapped_column(BigInteger)  # debit-positive

    __table_args__ = (UniqueConstraint("party_id", "variant_id"),)


__all__ = [
    "ContentPack",
    "PackVersion",
    "Variant",
    "Account",
    "Party",
    "SourceDocument",
    "AnswerKey",
    "PackAsset",
    "AccountOpeningBalance",
    "PartyOpeningBalance",
]
