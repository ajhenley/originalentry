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

#: For a template, which cannot import module constants: {"shape": 1, "lines": 2, "answer": 3}.
LEVELS = {"shape": LEVEL_SHAPE, "lines": LEVEL_LINES, "answer": LEVEL_ANSWER}

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

#: Roles carried only by the accounts ``problems.chapter`` synthesises to satisfy validator V5.
#: No chapter problem touches them, so they are kept out of the student's account picker.
SYNTHETIC_ONLY_ROLES = frozenset({"retained_earnings", "income_summary"})


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

    **An empty expectation never matches.** There is no key to compare against when a workspace
    has no variant (``variant_policy`` "manual" hands none out, so no AnswerKey row is found), and
    ``{} == {}`` used to answer True -- which told every student that every problem they had not
    started already matched. Absence of a key is not evidence of a match, the same way absence of
    a signature is not evidence of understanding.
    """
    if not expected:
        return False
    return expected == submitted


def shape_of_error(expected: dict, submitted: dict) -> str:
    """What *kind* of thing is wrong, naming neither a line nor an account.

    Checked in the order a reader would want: the wrong accounts entirely, then the right accounts
    on the wrong sides, then the right accounts and sides with a wrong figure. An entry that does
    not balance is reported as that first, since nothing else about it can be judged -- ``submit``
    refuses those, so it only arises for an entry recorded another way.

    With no key, there is no shape: saying "account" would have told a student with a perfect
    entry that one of their accounts did not belong, for ever.
    """
    if not expected:
        return SHAPE_MATCHED
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

def _manifest_problems(pack_version) -> list[dict]:
    return [d for d in (pack_version.manifest or {}).get("documents", [])]


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
    # The ref and the date come from the chapter, which is authoritative; the form carries only
    # the student's figures. A problem's date is a fact about the transaction, so asking a student
    # to type it would be a question with one right answer and a hidden field they could tamper
    # with -- and a date outside the pack's period is a refusal they could not act on.
    document = next(
        (d for d in _manifest_problems(pack_version) if d["ref"] == document_ref), None)
    payload = {
        **dict(form),
        "document_ref": document_ref,
        "kind": "regular",
        "entry_date": (document or {}).get("date", ""),
    }
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


# ── what a screen shows ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ProblemRow:
    """One problem on the chapter list."""

    ref: str
    stem: str
    attempts: int
    revealed: bool
    matched: bool

    @property
    def started(self) -> bool:
        return self.attempts > 0 or self.revealed


@dataclass(frozen=True)
class LineMark:
    """One line of the student's entry, and whether the key has it. Level 2 and above only."""

    account: str
    side: str
    cents: int
    in_the_key: bool


@dataclass(frozen=True)
class ProblemDetail:
    """One problem, and exactly as much about it as this student has earned.

    Each field above its level is empty rather than hidden by the template: a screen cannot leak
    what it was never given, and a template condition is one edit away from leaking everything.
    """

    ref: str
    stem: str
    #: The transaction's date, which the form validates against the pack's period.
    date: str
    #: False when this workspace has no answer key -- no variant was handed out -- so the screen
    #: can say why it is quiet instead of inventing a verdict.
    gradable: bool
    level: int
    attempts: int
    revealed: bool
    matched: bool
    shape: str
    #: The student's own entry, at any level.
    lines: tuple[LineMark, ...]
    #: Level 2 and above: which lines the key has. Empty below it.
    marked_lines: tuple[LineMark, ...]
    #: Level 2 and above: the pack's own sentence for the misconception it recognised.
    signatures: tuple[str, ...]
    #: Level 3 only, and only after the reveal button: the key's entry.
    answer: tuple[LineMark, ...]


def _key_for(session: Session, workspace: Workspace):
    """The answer key for this workspace's own variant, or None."""
    from ..models import AnswerKey
    from ..packs import schema

    row = session.scalars(
        select(AnswerKey).where(
            AnswerKey.pack_version_id == workspace.pack_version_id,
            AnswerKey.variant_id == workspace.variant_id,
        )
    ).one_or_none()
    return schema.load_answer_key(row.payload) if row is not None else None


def _expected_for(key, document_ref: str) -> dict:
    """The key's entry for one problem, merged the way the grader merges it."""
    from ..grading.components.documents import _key_amounts

    for entry in key.expected_entries if key else []:
        if entry.document == document_ref:
            return _key_amounts(entry)
    return {}


def _submitted_for(session: Session, workspace: Workspace, document_ref: str) -> dict:
    """The student's standing entry for one problem, merged the same way."""
    from ..models import Account

    entry = live_entry(session, workspace, document_ref)
    if entry is None:
        return {}
    merged: dict = {}
    for line in entry.lines:
        account = session.get(Account, line.account_id)
        side = "debit" if line.debit_cents else "credit"
        line_key = (account.number, None, side)
        merged[line_key] = merged.get(line_key, 0) + (line.debit_cents or line.credit_cents)
    return merged


def _as_lines(merged: dict, *, against: dict | None = None) -> tuple[LineMark, ...]:
    return tuple(
        LineMark(account=account, side=side, cents=cents,
                 in_the_key=(against is None or (account, party, side) in against))
        for (account, party, side), cents in sorted(merged.items())
    )


def chapter_problems(session: Session, workspace: Workspace) -> list[ProblemRow]:
    """Every problem in the chapter, with this student's state for each.

    No mark, running or otherwise: ``student/views.py`` shows a student nothing about marks until
    ``Assignment.marks_released_at``, and a problem set does not get to be the exception.
    """
    rows = attempts_for(session, workspace)
    key = _key_for(session, workspace)
    out: list[ProblemRow] = []
    for document in _manifest_problems(workspace_pack_version(session, workspace)):
        ref = document["ref"]
        attempt = rows.get(ref)
        out.append(ProblemRow(
            ref=ref,
            stem=document.get("stem") or "",
            attempts=attempt.attempts if attempt else 0,
            revealed=bool(attempt and attempt.answer_shown_at),
            matched=matches(_expected_for(key, ref), _submitted_for(session, workspace, ref)),
        ))
    return out


def workspace_pack_version(session: Session, workspace: Workspace) -> PackVersion:
    return session.get(PackVersion, workspace.pack_version_id)


def chart(session: Session, workspace: Workspace) -> list[Account]:
    """The accounts a student picks from.

    Only the ones the chapter declares: ``problems.chapter`` synthesises a retained-earnings and
    an income-summary account to satisfy V5, and neither belongs in a picker for a chapter whose
    problems do not touch them.
    """
    return [
        account for account in session.scalars(
            select(Account)
            .where(Account.pack_version_id == workspace.pack_version_id)
            .order_by(Account.sort_order, Account.number)).all()
        if not set(account.roles or []) & SYNTHETIC_ONLY_ROLES
    ]


def problem_detail(
    session: Session, workspace: Workspace, document_ref: str
) -> ProblemDetail | None:
    """One problem, or None if this chapter has no such problem."""
    document = next(
        (d for d in _manifest_problems(workspace_pack_version(session, workspace))
         if d["ref"] == document_ref),
        None,
    )
    if document is None:
        return None

    attempt = attempt_for(session, workspace, document_ref)
    level = feedback_level(attempt)
    key = _key_for(session, workspace)
    expected = _expected_for(key, document_ref)
    submitted = _submitted_for(session, workspace, document_ref)
    matched = matches(expected, submitted)
    # No key: no marks, no comparison, and nothing to reveal. The screen says so rather than
    # offering a reveal button that would forfeit the problem and then show an empty table.
    gradable = bool(expected)

    return ProblemDetail(
        ref=document_ref,
        stem=document.get("stem") or "",
        date=document.get("date") or "",
        gradable=gradable,
        level=level,
        attempts=attempt.attempts if attempt else 0,
        revealed=bool(attempt and attempt.answer_shown_at),
        matched=matched,
        # Nothing to diagnose before the first attempt, or once it matches.
        shape="" if (matched or not submitted) else shape_of_error(expected, submitted),
        lines=_as_lines(submitted),
        marked_lines=(
            _as_lines(submitted, against=expected)
            if gradable and level >= LEVEL_LINES else ()
        ),
        signatures=(
            _signatures_for(session, workspace, key, document_ref)
            if gradable and level >= LEVEL_LINES else ()
        ),
        answer=_as_lines(expected) if gradable and level >= LEVEL_ANSWER else (),
    )


def _signatures_for(session: Session, workspace: Workspace, key, document_ref: str):
    """The pack's own sentences for the misconceptions it recognised in this problem.

    T8.8 says a signature never reaches the student. It is exempted here, behind the fence in
    ``decorators.PROBLEM_SET_ENDPOINTS`` and only from the second attempt -- which is the whole
    point of a self-grading problem, and why the label is prose the author wrote rather than a key
    the engine made up.
    """
    from ..grading.signatures import detect
    from ..grading.workspace import load_work
    from ..packs import schema

    if key is None:
        return ()
    pack = schema.load_pack(workspace_pack_version(session, workspace).manifest)
    found, _unexplained = detect(load_work(session, workspace), pack, key)
    mine = {
        signature.key for signature in key.error_signatures
        if (signature.detect or {}).get("document") == document_ref
    }
    return tuple(found_one.label for found_one in found if found_one.key in mine)
