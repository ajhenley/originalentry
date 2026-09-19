"""Work tables (D4). Created by students and staff. Every row carries ``workspace_id``; rows
that reference content also carry ``pack_version_id`` for the composite foreign keys that make a
forgotten scope fail loudly (D5, D6 rule 5).

Worksheet and grade tables land later; assignment sub-tables
(choices, checkpoints, overrides, availability) land with the staff console. This module is the
core chain that the ledger engine's snapshot reads.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db
from ..ids import new_public_id

# Entry kinds and posting targets mirror the engine's vocabulary.
KIND_REGULAR = "regular"
KIND_ADJUSTING = "adjusting"
KIND_CLOSING = "closing"

TARGET_GENERAL = "general"
TARGET_SUBSIDIARY = "subsidiary"

LATE_CLOSED = "closed"
LATE_ACCEPT = "accept_late"


class Assignment(db.Model):
    __tablename__ = "assignment"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(10), unique=True, default=new_public_id)
    section_id: Mapped[int] = mapped_column(ForeignKey("section.id"))
    title: Mapped[str] = mapped_column(String(200))
    mode: Mapped[str] = mapped_column(String(20), default="screen")  # screen | paper
    company_policy: Mapped[str] = mapped_column(String(20), default="fixed")  # fixed | choice
    fixed_pack_version_id: Mapped[int | None] = mapped_column(ForeignKey("pack_version.id"))
    variant_policy: Mapped[str] = mapped_column(String(20), default="assigned")
    opens_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    late_policy: Mapped[str] = mapped_column(String(20), default=LATE_CLOSED)
    late_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    prerequisite_assignment_id: Mapped[int | None] = mapped_column(ForeignKey("assignment.id"))
    guided_mode: Mapped[bool] = mapped_column(Boolean, default=True)
    cloned_from_id: Mapped[int | None] = mapped_column(ForeignKey("assignment.id"))
    marks_released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        # A fixed policy requires a pack version; accept_late requires late_until > due_at (D4).
        CheckConstraint(
            "(company_policy <> 'fixed') OR (fixed_pack_version_id IS NOT NULL)",
            name="assignment_fixed_requires_version",
        ),
        CheckConstraint(
            "(late_policy <> 'accept_late') OR (late_until IS NOT NULL AND late_until > due_at)",
            name="assignment_accept_late_requires_until",
        ),
    )


class SectionPackAvailability(db.Model):
    """Which companies a section may use (M1.4). Checked when a workspace is created or a company
    is chosen — never mid-work, so withdrawing a company leaves existing workspaces usable (A22)."""

    __tablename__ = "section_pack_availability"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    section_id: Mapped[int] = mapped_column(ForeignKey("section.id"))
    content_pack_id: Mapped[int] = mapped_column(ForeignKey("content_pack.id"))
    status: Mapped[str] = mapped_column(String(20), default="available")  # available | withdrawn

    __table_args__ = (UniqueConstraint("section_id", "content_pack_id"),)


class AssignmentChoice(db.Model):
    """A pack version a student may choose for a choice assignment (tension 4)."""

    __tablename__ = "assignment_choice"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("assignment.id"))
    pack_version_id: Mapped[int] = mapped_column(ForeignKey("pack_version.id"))

    __table_args__ = (UniqueConstraint("assignment_id", "pack_version_id"),)


class Workspace(db.Model):
    __tablename__ = "workspace"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(10), unique=True, default=new_public_id)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("assignment.id"))
    student_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    pack_version_id: Mapped[int] = mapped_column(ForeignKey("pack_version.id"))
    variant_id: Mapped[int] = mapped_column(ForeignKey("variant.id"))
    status: Mapped[str] = mapped_column(String(20), default="not_started")
    version: Mapped[int] = mapped_column(BigInteger, default=0)
    company_chosen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_late_hours: Mapped[int | None] = mapped_column(Integer)
    reopened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("id", "pack_version_id"),  # composite-FK target (D5)
        # One live workspace per (assignment, student); archived ones do not collide.
        Index(
            "uq_workspace_assignment_student_live",
            "assignment_id",
            "student_id",
            unique=True,
            postgresql_where=db.text("archived_at IS NULL"),
        ),
    )


class Disposition(db.Model):
    __tablename__ = "disposition"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(BigInteger)
    pack_version_id: Mapped[int] = mapped_column(BigInteger)
    document_id: Mapped[int] = mapped_column(BigInteger)
    choice: Mapped[str] = mapped_column(String(20))  # record | no_entry
    reason: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "pack_version_id"],
            ["workspace.id", "workspace.pack_version_id"],
            deferrable=True,
            initially="DEFERRED",
            name="disposition_workspace_scope",
        ),
        ForeignKeyConstraint(
            ["pack_version_id", "document_id"],
            ["source_document.pack_version_id", "source_document.id"],
            deferrable=True,
            initially="DEFERRED",
            name="disposition_document_scope",
        ),
        # One current row per document (superseded rows keep their history, tension 9).
        Index(
            "uq_disposition_current",
            "workspace_id",
            "document_id",
            unique=True,
            postgresql_where=db.text("superseded_at IS NULL"),
        ),
        CheckConstraint(
            "(choice <> 'no_entry') OR "
            "(reason IS NOT NULL AND char_length(reason) BETWEEN 1 AND 200)",
            name="disposition_no_entry_needs_reason",
        ),
    )


class JournalEntry(db.Model):
    __tablename__ = "journal_entry"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(10), unique=True, default=new_public_id)
    workspace_id: Mapped[int] = mapped_column(BigInteger)
    pack_version_id: Mapped[int] = mapped_column(BigInteger)
    journal_key: Mapped[str] = mapped_column(String(40))
    seq: Mapped[int] = mapped_column(Integer, default=0)
    entry_date: Mapped[date] = mapped_column(Date)
    document_id: Mapped[int | None] = mapped_column(BigInteger)
    description: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(12))  # regular | adjusting | closing
    client_key: Mapped[str] = mapped_column(String(64))
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    void_reason: Mapped[str | None] = mapped_column(Text)

    lines: Mapped[list[EntryLine]] = relationship(
        back_populates="entry", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("workspace_id", "client_key"),  # idempotency (T7.4)
        ForeignKeyConstraint(
            ["workspace_id", "pack_version_id"],
            ["workspace.id", "workspace.pack_version_id"],
            deferrable=True,
            initially="DEFERRED",
            name="journal_entry_workspace_scope",
        ),
        ForeignKeyConstraint(
            ["pack_version_id", "document_id"],
            ["source_document.pack_version_id", "source_document.id"],
            deferrable=True,
            initially="DEFERRED",
            name="journal_entry_document_scope",
        ),
        CheckConstraint(
            "kind IN ('regular', 'adjusting', 'closing')", name="journal_entry_kind"
        ),
    )


class JournalEntryRevision(db.Model):
    __tablename__ = "journal_entry_revision"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("journal_entry.id"))
    snapshot: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EntryLine(db.Model):
    __tablename__ = "entry_line"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("journal_entry.id"))
    workspace_id: Mapped[int] = mapped_column(BigInteger)
    pack_version_id: Mapped[int] = mapped_column(BigInteger)
    line_no: Mapped[int] = mapped_column(Integer)
    column_key: Mapped[str | None] = mapped_column(String(40))
    account_id: Mapped[int] = mapped_column(BigInteger)
    party_id: Mapped[int | None] = mapped_column(BigInteger)
    debit_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    credit_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    memo: Mapped[str | None] = mapped_column(Text)

    entry: Mapped[JournalEntry] = relationship(back_populates="lines")

    __table_args__ = (
        # A line is a debit or a credit, never both, never zero (D5).
        CheckConstraint(
            "debit_cents >= 0 AND credit_cents >= 0 "
            "AND ((debit_cents = 0) <> (credit_cents = 0))",
            name="entry_line_one_side",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "pack_version_id"],
            ["workspace.id", "workspace.pack_version_id"],
            deferrable=True,
            initially="DEFERRED",
            name="entry_line_workspace_scope",
        ),
        ForeignKeyConstraint(
            ["pack_version_id", "account_id"],
            ["account.pack_version_id", "account.id"],
            deferrable=True,
            initially="DEFERRED",
            name="entry_line_account_scope",
        ),
        ForeignKeyConstraint(
            ["pack_version_id", "party_id"],
            ["party.pack_version_id", "party.id"],
            deferrable=True,
            initially="DEFERRED",
            name="entry_line_party_scope",
        ),
    )


class PostingRun(db.Model):
    __tablename__ = "posting_run"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(10), unique=True, default=new_public_id)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id"))
    journal_key: Mapped[str] = mapped_column(String(40))
    target: Mapped[str] = mapped_column(String(12))  # general | subsidiary
    ordinal: Mapped[int] = mapped_column(Integer)
    client_key: Mapped[str] = mapped_column(String(64))
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reversal_reason: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("workspace_id", "client_key"),
        CheckConstraint("target IN ('general', 'subsidiary')", name="posting_run_target"),
    )


class CheckpointAttempt(db.Model):
    __tablename__ = "checkpoint_attempt"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id"))
    checkpoint_key: Mapped[str] = mapped_column(String(40))
    attempt_no: Mapped[int] = mapped_column(Integer)
    value_cents: Mapped[int] = mapped_column(BigInteger)  # the student's submitted figure
    passed: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("workspace_id", "checkpoint_key", "attempt_no"),
    )


class ActivityEvent(db.Model):
    __tablename__ = "activity_event"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id"))
    kind: Mapped[str] = mapped_column(String(20))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # detail holds IDs and references only, never personal data (D4).
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)

    __table_args__ = (Index("ix_activity_event_workspace", "workspace_id", "at"),)


class StatementDraft(db.Model):
    """One student-built statement (S5.5). The rows are the student's own layout."""

    __tablename__ = "statement_draft"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id"))
    statement_type: Mapped[str] = mapped_column(String(40))
    header: Mapped[dict] = mapped_column(JSONB, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    lines: Mapped[list[StatementLine]] = relationship(
        back_populates="draft",
        cascade="all, delete-orphan",
        order_by="StatementLine.position",
    )

    __table_args__ = (UniqueConstraint("workspace_id", "statement_type"),)


class StatementLine(db.Model):
    """A row of a statement: heading, account, subtotal, total or blank.

    Subtotal and total rows name a ``subtotal_type`` from the pack, so the grading engine can
    read the structure without guessing at free text (tension 7). The label of a heading is the
    student's own words and is not graded.
    """

    __tablename__ = "statement_line"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("statement_draft.id"))
    workspace_id: Mapped[int] = mapped_column(BigInteger)
    pack_version_id: Mapped[int] = mapped_column(BigInteger)
    position: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(12))
    label: Mapped[str | None] = mapped_column(Text)
    subtotal_type: Mapped[str | None] = mapped_column(String(40))
    account_id: Mapped[int | None] = mapped_column(BigInteger)
    amount_cents: Mapped[int | None] = mapped_column(BigInteger)  # negative = shown in parentheses
    indent: Mapped[int] = mapped_column(Integer, default=0)
    amount_column: Mapped[int] = mapped_column(Integer, default=1)

    draft: Mapped[StatementDraft] = relationship(back_populates="lines")

    __table_args__ = (
        UniqueConstraint("draft_id", "position"),
        CheckConstraint(
            "kind IN ('heading', 'account', 'subtotal', 'total', 'blank')",
            name="statement_line_kind",
        ),
        CheckConstraint(
            "(kind <> 'account') OR (account_id IS NOT NULL)",
            name="statement_line_account_row_needs_account",
        ),
        CheckConstraint(
            "(kind NOT IN ('subtotal', 'total')) OR (subtotal_type IS NOT NULL)",
            name="statement_line_subtotal_row_needs_type",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "pack_version_id"],
            ["workspace.id", "workspace.pack_version_id"],
            deferrable=True,
            initially="DEFERRED",
            name="statement_line_workspace_scope",
        ),
        ForeignKeyConstraint(
            ["pack_version_id", "account_id"],
            ["account.pack_version_id", "account.id"],
            deferrable=True,
            initially="DEFERRED",
            name="statement_line_account_scope",
        ),
    )


class GradeRun(db.Model):
    """One run of the grading engine (T8.1). Immutable: regrading adds a run, never edits one."""

    __tablename__ = "grade_run"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id"))
    pack_version_id: Mapped[int] = mapped_column(BigInteger)
    variant_id: Mapped[int] = mapped_column(BigInteger)
    engine_version: Mapped[str] = mapped_column(String(20))
    total_points: Mapped[int] = mapped_column(BigInteger)  # hundredths of a point
    max_points: Mapped[int] = mapped_column(BigInteger)  # hundredths of a point
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    submission_status: Mapped[str] = mapped_column(String(20), default="open")
    results: Mapped[dict] = mapped_column(JSONB)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def result(self):
        """The stored result as the engine's own dataclasses (imported here to avoid a cycle)."""
        from ..grading.models import result_from_dict

        return result_from_dict(self.results or {})

    __table_args__ = (
        Index("ix_grade_run_workspace", "workspace_id", "created_at"),
        CheckConstraint(
            "submission_status IN ('open', 'submitted', 'submitted_late', 'not_submitted')",
            name="grade_run_submission_status",
        ),
    )


class GradeOverride(db.Model):
    """An instructor's judgement on one component. It outlives every later run (A12)."""

    __tablename__ = "grade_override"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id"))
    component_key: Mapped[str] = mapped_column(String(40))
    points: Mapped[int] = mapped_column(BigInteger)  # hundredths of a point
    reason: Mapped[str] = mapped_column(Text)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index(
            "uq_grade_override_current",
            "workspace_id",
            "component_key",
            unique=True,
            postgresql_where=db.text("superseded_at IS NULL"),
        ),
    )


class GradeComment(db.Model):
    """The instructor's words to the student, shown once marks are released (I3.5)."""

    __tablename__ = "grade_comment"

    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id"), primary_key=True)
    body: Mapped[str] = mapped_column(Text)
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PostingRunEntry(db.Model):
    __tablename__ = "posting_run_entry"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    posting_run_id: Mapped[int] = mapped_column(ForeignKey("posting_run.id"))
    entry_id: Mapped[int] = mapped_column(ForeignKey("journal_entry.id"))
    target: Mapped[str] = mapped_column(String(12))
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (
        # An entry cannot be actively posted twice to the same target.
        Index(
            "uq_posting_run_entry_active",
            "entry_id",
            "target",
            unique=True,
            postgresql_where=db.text("active"),
        ),
    )


__all__ = [
    "Assignment",
    "SectionPackAvailability",
    "AssignmentChoice",
    "Workspace",
    "Disposition",
    "JournalEntry",
    "JournalEntryRevision",
    "EntryLine",
    "PostingRun",
    "PostingRunEntry",
    "CheckpointAttempt",
    "StatementDraft",
    "StatementLine",
    "GradeRun",
    "GradeOverride",
    "GradeComment",
    "ActivityEvent",
    "KIND_REGULAR",
    "KIND_ADJUSTING",
    "KIND_CLOSING",
    "TARGET_GENERAL",
    "TARGET_SUBSIDIARY",
    "LATE_CLOSED",
    "LATE_ACCEPT",
]
