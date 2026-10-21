"""Attempts at a chapter problem, and how much each one earns the student.

Three things live here, and each exists to stop a specific way this feature could be unkind.

**The attempt count is a row, never a number a page carries.** A counter the browser owns is one a
student could reset by reloading, which would turn progressive disclosure into pressing submit
twice.

**A refused submission costs nothing.** An entry that does not balance never reaches the attempt
row: an attempt lost to a typo is a defect, not the price of practising. The balance check is the
one in ``forms.entries``, not a second one written here -- two answers to the same question
eventually disagree.

**Submitting replaces.** The previous entry for the problem is voided, so a problem never has two
entries that still stand. ``grading.components.problems`` asks for review when one does, and
without this every problem a student tried twice would ask for it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..forms.entries import AccountInfo, EntryContext, parse_general_entry
from ..models import (
    Account,
    JournalEntry,
    PackVersion,
    Party,
    ProblemAttempt,
    SourceDocument,
    Workspace,
)
from .entries import record_entry, void_entry

#: How much a student is shown. Ordered so a template can compare them.
LEVEL_SHAPE = 1  # which kind of thing is wrong; never which line
LEVEL_LINES = 2  # per-line marks and the signature's sentence
LEVEL_ANSWER = 3  # the expected entry; only after an explicit reveal

#: What kind of thing is wrong, at LEVEL_SHAPE. Deliberately coarse: naming the line would make
#: attempt one into attempt two, and a student would never have to look at their own work.
SHAPE_MATCHED = ""
SHAPE_BALANCE = "balance"
SHAPE_ACCOUNT = "account"
SHAPE_DIRECTION = "direction"
SHAPE_AMOUNT = "amount"

#: Why the previous entry was voided. A student sees this nowhere; it is for a staff member
#: reading the entry history and wondering where an entry went.
REPLACED = "Replaced by a later attempt at this problem."

#: Only the general journal: a chapter problem set has one journal and no special journals.
JOURNAL_KEY = "general"


@dataclass(frozen=True)
class Submission:
    """What one submission did. ``accepted`` is false for a refusal that cost nothing."""

    accepted: bool
    attempt: ProblemAttempt | None = None
    entry: JournalEntry | None = None
    errors: tuple[tuple[str, str], ...] = field(default_factory=tuple)


# ── what to show ───────────────────────────────────────────────────────────────────────

def feedback_level(attempt: ProblemAttempt | None) -> int:
    """How much this student has earned the right to see for this problem."""
    if attempt is None:
        return LEVEL_SHAPE
    if attempt.answer_shown_at is not None:
        return LEVEL_ANSWER
    return LEVEL_LINES if attempt.attempts >= 2 else LEVEL_SHAPE


def matches(expected: dict, submitted: dict) -> bool:
    """Whether the entry is the key's entry, with lines already merged by (account, party, side).

    The merge is what makes splitting one line across two not a mistake (T8.3); it happens in
    ``grading.components.documents`` before this sees either side.
    """
    return expected == submitted


def shape_of_error(expected: dict, submitted: dict) -> str:
    """What *kind* of thing is wrong, naming neither a line nor an account.

    Checked in the order a reader would want: the wrong accounts entirely, then the right accounts
    on the wrong sides, then the right accounts and sides with a wrong figure. An entry that does
    not balance is reported as that first, since nothing else about it can be judged -- ``submit``
    refuses those, so it only arises for an entry recorded another way.
    """
    if matches(expected, submitted):
        return SHAPE_MATCHED

    debits = sum(cents for (_a, _p, side), cents in submitted.items() if side == "debit")
    credits = sum(cents for (_a, _p, side), cents in submitted.items() if side == "credit")
    if debits != credits:
        return SHAPE_BALANCE

    if {account for account, _p, _s in expected} != {account for account, _p, _s in submitted}:
        return SHAPE_ACCOUNT
    if set(expected) != set(submitted):
        return SHAPE_DIRECTION
    return SHAPE_AMOUNT


# ── the attempt row ────────────────────────────────────────────────────────────────────

def attempt_for(session: Session, workspace: Workspace, document_ref: str) -> ProblemAttempt | None:
    return session.scalars(
        select(ProblemAttempt).where(
            ProblemAttempt.workspace_id == workspace.id,
            ProblemAttempt.document_ref == document_ref,
        )
    ).one_or_none()


def attempts_for(session: Session, workspace: Workspace) -> dict[str, ProblemAttempt]:
    """Every problem's row for one workspace, which is how the list screen reads them."""
    return {
        row.document_ref: row
        for row in session.scalars(
            select(ProblemAttempt).where(ProblemAttempt.workspace_id == workspace.id)).all()
    }


def _attempt_row(session: Session, workspace: Workspace, document_ref: str) -> ProblemAttempt:
    existing = attempt_for(session, workspace, document_ref)
    if existing is not None:
        return existing
    row = ProblemAttempt(workspace_id=workspace.id, document_ref=document_ref, attempts=0)
    session.add(row)
    session.flush()
    return row


# ── submitting ─────────────────────────────────────────────────────────────────────────

def entry_context(session: Session, pack_version: PackVersion) -> EntryContext:
    """The context ``forms.entries`` validates against, built from a session rather than from
    ``g`` -- so the same validation runs in a service, a test and a CLI command."""
    accounts = session.scalars(
        select(Account).where(Account.pack_version_id == pack_version.id)).all()
    return EntryContext(
        journal_key=JOURNAL_KEY,
        accounts={a.number: AccountInfo(a.number, a.subsidiary_kind) for a in accounts},
        party_codes=set(session.scalars(
            select(Party.code).where(Party.pack_version_id == pack_version.id)).all()),
        period_start=pack_version.period_start,
        period_end=pack_version.period_end,
        period_label="",
        document_refs=set(session.scalars(
            select(SourceDocument.ref).where(
                SourceDocument.pack_version_id == pack_version.id)).all()),
    )


def entries_for(session: Session, workspace: Workspace, document_ref: str) -> list[JournalEntry]:
    """Every entry this workspace has for one problem, voided ones included.

    ``JournalEntry`` carries ``document_id``, not a ref -- the composite foreign key is what makes
    a forgotten scope fail loudly (D6 rule 5) -- so the ref is resolved through SourceDocument,
    itself scoped to the workspace's pack version.
    """
    return list(session.scalars(
        select(JournalEntry)
        .join(SourceDocument, SourceDocument.id == JournalEntry.document_id)
        .where(
            JournalEntry.workspace_id == workspace.id,
            SourceDocument.pack_version_id == workspace.pack_version_id,
            SourceDocument.ref == document_ref,
        ).order_by(JournalEntry.id)
    ).all())


def live_entry(session: Session, workspace: Workspace, document_ref: str) -> JournalEntry | None:
    """The one entry for this problem that still stands."""
    standing = [e for e in entries_for(session, workspace, document_ref) if e.voided_at is None]
    return standing[-1] if standing else None


def submit(
    session: Session, workspace: Workspace, document_ref: str, form, *, actor=None
) -> Submission:
    """Record an attempt at one problem, replacing whatever stood for it before.

    A refusal -- an entry that does not balance, one line, an account the pack does not have --
    returns ``accepted=False`` and touches nothing: not the attempt count, not the disclosure
    level, not the student's previous entry. That is the whole of "an attempt lost to a typo is a
    defect".
    """
    pack_version = session.get(PackVersion, workspace.pack_version_id)
    # The ref comes from the URL, which is authoritative; the form is the student's figures.
    payload = {**dict(form), "document_ref": document_ref, "kind": "regular"}
    result = parse_general_entry(payload, entry_context(session, pack_version))

    if not result.ok:
        return Submission(
            accepted=False,
            attempt=attempt_for(session, workspace, document_ref),
            errors=tuple(result.errors),
        )

    previous = live_entry(session, workspace, document_ref)
    if previous is not None:
        void_entry(session, workspace, previous.public_id, REPLACED)

    entry = record_entry(session, workspace, result.command)
    attempt = _attempt_row(session, workspace, document_ref)
    attempt.attempts += 1
    attempt.last_submitted_at = datetime.now(UTC)
    session.flush()
    return Submission(accepted=True, attempt=attempt, entry=entry)


# ── revealing ──────────────────────────────────────────────────────────────────────────

def reveal(
    session: Session, workspace: Workspace, document_ref: str, *, actor=None
) -> ProblemAttempt:
    """Show this student the expected entry, and stop the problem counting.

    The only path to ``LEVEL_ANSWER``: A8 is exempted for problem sets behind this button and
    nowhere else. Idempotent, and never undone -- a later submission is still practice, and the
    problem stays practisable, but it does not come back to life for the mark.
    """
    attempt = _attempt_row(session, workspace, document_ref)
    if attempt.answer_shown_at is None:
        attempt.answer_shown_at = datetime.now(UTC)
        session.flush()
    return attempt
