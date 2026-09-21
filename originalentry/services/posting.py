"""Posting writes (T6.4): post a journal to the general ledger, post entries to the subsidiary
ledger (single or all), and reverse a run. Called inside :func:`workspace_write`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import messages
from ..models import (
    TARGET_GENERAL,
    TARGET_SUBSIDIARY,
    EntryLine,
    JournalEntry,
    PostingRun,
    PostingRunEntry,
    Workspace,
)
from .errors import WriteRefused


def active_posted_entry_ids(session: Session, workspace: Workspace, target: str) -> set[int]:
    """Entry ids currently posted to ``target`` (active run entries, un-reversed runs)."""
    rows = session.execute(
        select(PostingRunEntry.entry_id)
        .join(PostingRun, PostingRunEntry.posting_run_id == PostingRun.id)
        .where(
            PostingRun.workspace_id == workspace.id,
            PostingRunEntry.target == target,
            PostingRunEntry.active.is_(True),
            PostingRun.reversed_at.is_(None),
        )
    ).scalars()
    return set(rows)


def outstanding_postings(
    session: Session, workspace: Workspace, journal_keys: list[str]
) -> dict[str, dict[str, int]]:
    """Per journal, how much of it is recorded but not yet posted.

    Two separate counts, because the two ledgers are posted by two separate actions: entries not
    in the general ledger, and entries carrying a party that are not in a subsidiary ledger. A
    voided entry is neither, and never will be, so it is not something left to do.
    """
    general = active_posted_entry_ids(session, workspace, TARGET_GENERAL)
    subsidiary = active_posted_entry_ids(session, workspace, TARGET_SUBSIDIARY)
    counts: dict[str, dict[str, int]] = {}
    for key in journal_keys:
        entries = _live_entries(session, workspace, key)
        with_party = _entry_ids_with_party(session, [e.id for e in entries])
        counts[key] = {
            "general": sum(1 for e in entries if e.id not in general),
            "subsidiary": sum(1 for e in entries
                              if e.id in with_party and e.id not in subsidiary),
        }
    return counts


def _next_ordinal(session: Session, workspace: Workspace, journal_key: str, target: str) -> int:
    return session.execute(
        select(func.coalesce(func.max(PostingRun.ordinal), 0) + 1).where(
            PostingRun.workspace_id == workspace.id,
            PostingRun.journal_key == journal_key,
            PostingRun.target == target,
        )
    ).scalar_one()


def _live_entries(session: Session, workspace: Workspace, journal_key: str) -> list[JournalEntry]:
    return list(
        session.scalars(
            select(JournalEntry)
            .where(
                JournalEntry.workspace_id == workspace.id,
                JournalEntry.journal_key == journal_key,
                JournalEntry.voided_at.is_(None),
            )
            .order_by(JournalEntry.seq)
        )
    )


def _entry_ids_with_party(session: Session, entry_ids: list[int]) -> set[int]:
    if not entry_ids:
        return set()
    rows = session.execute(
        select(EntryLine.entry_id)
        .where(EntryLine.entry_id.in_(entry_ids), EntryLine.party_id.is_not(None))
        .distinct()
    ).scalars()
    return set(rows)


def _open_run(
    session: Session, workspace: Workspace, journal_key: str, target: str, entries: list[int]
) -> PostingRun:
    run = PostingRun(
        workspace_id=workspace.id,
        journal_key=journal_key,
        target=target,
        ordinal=_next_ordinal(session, workspace, journal_key, target),
        client_key=uuid.uuid4().hex,
    )
    session.add(run)
    session.flush()
    for entry_id in entries:
        session.add(
            PostingRunEntry(
                posting_run_id=run.id, entry_id=entry_id, target=target, active=True
            )
        )
    session.flush()
    return run


def post_journal_general(session: Session, workspace: Workspace, journal_key: str) -> PostingRun:
    """Post every non-void, unposted entry in the journal to the general ledger."""
    posted = active_posted_entry_ids(session, workspace, TARGET_GENERAL)
    entries = [e.id for e in _live_entries(session, workspace, journal_key) if e.id not in posted]
    if not entries:
        raise WriteRefused(messages.JOURNAL_ALREADY_POSTED)
    return _open_run(session, workspace, journal_key, TARGET_GENERAL, entries)


def post_entry_subsidiary(
    session: Session, workspace: Workspace, entry_public_id: str
) -> PostingRun:
    entry = session.execute(
        select(JournalEntry).where(
            JournalEntry.workspace_id == workspace.id,
            JournalEntry.public_id == entry_public_id,
            JournalEntry.voided_at.is_(None),
        )
    ).scalar_one_or_none()
    if entry is None:
        raise WriteRefused(messages.ENTRY_ALREADY_SUBSIDIARY_POSTED)
    if not _entry_ids_with_party(session, [entry.id]):
        raise WriteRefused(messages.ENTRY_ALREADY_SUBSIDIARY_POSTED)
    if entry.id in active_posted_entry_ids(session, workspace, TARGET_SUBSIDIARY):
        raise WriteRefused(messages.ENTRY_ALREADY_SUBSIDIARY_POSTED)
    return _open_run(session, workspace, entry.journal_key, TARGET_SUBSIDIARY, [entry.id])


def post_journal_subsidiary_all(
    session: Session, workspace: Workspace, journal_key: str
) -> PostingRun:
    """Post every eligible (party-bearing, non-void, unposted) entry in the journal as one run."""
    posted = active_posted_entry_ids(session, workspace, TARGET_SUBSIDIARY)
    live = _live_entries(session, workspace, journal_key)
    with_party = _entry_ids_with_party(session, [e.id for e in live])
    entries = [e.id for e in live if e.id in with_party and e.id not in posted]
    if not entries:
        raise WriteRefused(messages.JOURNAL_SUBSIDIARY_ALREADY_POSTED)
    return _open_run(session, workspace, journal_key, TARGET_SUBSIDIARY, entries)


def reverse_run(
    session: Session, workspace: Workspace, run_public_id: str, reason: str
) -> PostingRun:
    run = session.execute(
        select(PostingRun).where(
            PostingRun.workspace_id == workspace.id,
            PostingRun.public_id == run_public_id,
            PostingRun.reversed_at.is_(None),
        )
    ).scalar_one_or_none()
    if run is None:
        raise WriteRefused(messages.JOURNAL_ALREADY_POSTED)
    run.reversed_at = datetime.now(UTC)
    run.reversal_reason = reason
    for pre in session.scalars(
        select(PostingRunEntry).where(PostingRunEntry.posting_run_id == run.id)
    ):
        pre.active = False
    return run
