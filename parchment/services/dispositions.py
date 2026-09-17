"""Disposition (triage) writes. A student decides, per source document, whether to record an
entry or that no entry is required. Called inside :func:`workspace_write`.

One current row per document (a partial unique index enforces it); choosing again supersedes the
old row rather than deleting it, so the history stays (tension 9).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .. import messages
from ..models import Disposition, SourceDocument, Workspace
from .errors import WriteRefused

CHOICE_RECORD = "record"
CHOICE_NO_ENTRY = "no_entry"


def set_disposition(
    session: Session, workspace: Workspace, document_ref: str, choice: str, reason: str | None
) -> Disposition:
    document_id = session.execute(
        select(SourceDocument.id).where(
            SourceDocument.pack_version_id == workspace.pack_version_id,
            SourceDocument.ref == document_ref,
        )
    ).scalar_one_or_none()
    if document_id is None:
        raise WriteRefused(messages.ENTRY_NEEDS_DOCUMENT)

    reason = (reason or "").strip() or None
    if choice == CHOICE_NO_ENTRY:
        if reason is None or not (1 <= len(reason) <= 200):
            raise WriteRefused(messages.NO_ENTRY_NEEDS_REASON)
    else:
        choice = CHOICE_RECORD
        reason = None

    # Supersede any current row for this document before inserting the new one, so the partial
    # unique index (one current row per document) is never violated.
    session.execute(
        update(Disposition)
        .where(
            Disposition.workspace_id == workspace.id,
            Disposition.document_id == document_id,
            Disposition.superseded_at.is_(None),
        )
        .values(superseded_at=datetime.now(UTC))
    )
    session.flush()

    disposition = Disposition(
        workspace_id=workspace.id,
        pack_version_id=workspace.pack_version_id,
        document_id=document_id,
        choice=choice,
        reason=reason,
    )
    session.add(disposition)
    session.flush()
    return disposition


def current_dispositions(session: Session, workspace: Workspace) -> dict[int, Disposition]:
    """Map document_id -> current disposition for this workspace."""
    rows = session.scalars(
        select(Disposition).where(
            Disposition.workspace_id == workspace.id, Disposition.superseded_at.is_(None)
        )
    )
    return {d.document_id: d for d in rows}
