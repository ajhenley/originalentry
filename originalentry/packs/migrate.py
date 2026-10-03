"""Migrating a running assignment to a newer pack version (I1, T5.5, Should).

A pack version is immutable once used, so a correction is always a new version. This moves an
assignment's existing workspaces onto that new version, re-pointing every work row at the new
version's accounts, parties, documents and variants by their natural keys (number, code, ref,
variant code). It is allowed only if every one of those a student has already used still exists
in the new version — otherwise their work would be orphaned, and the migration is refused.

Existing is not the same as unchanged. A pack rebuilt from its printed envelope can give the same
base ref to a different artefact — the printed set hands a ref to whichever document arrived
first, so a transaction's invoice can become a sibling and its purchase order can inherit the
number. A ref a student used can therefore survive a rebuild while denoting something else
entirely, which no amount of remapping fixes, so the migration is refused for that too unless
``--accept-identity-changes`` says it was deliberate.

Always dry-run first: the report says whether it is feasible and what it would touch. The real
run remaps in one transaction (the composite foreign keys are deferrable, so the version and the
id move together) and logs a staff action. Restricted to fixed-company assignments.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Account,
    Assignment,
    Disposition,
    EntryLine,
    JournalEntry,
    PackVersion,
    Party,
    SourceDocument,
    StatementLine,
    Variant,
    Workspace,
)
from ..models import AnswerKey as AnswerKeyRow
from ..services import staff_actions
from .version_diff import IdentityChange, identity_changes


class MigrationRefused(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


@dataclass
class MigrationReport:
    from_version: int
    to_version: int
    workspaces: int = 0
    entry_lines: int = 0
    missing_accounts: list[str] = field(default_factory=list)
    missing_parties: list[str] = field(default_factory=list)
    missing_documents: list[str] = field(default_factory=list)
    missing_variants: list[str] = field(default_factory=list)
    #: Refs the student used that denote a different document in the new version. Always populated:
    #: accepting them does not make them untrue, and a caller reading this field must see what
    #: happened whether or not the override was passed.
    changed_identity: list[IdentityChange] = field(default_factory=list)
    #: Set when --accept-identity-changes was given. Acceptance is recorded here rather than by
    #: emptying the list above, so nothing has to read two fields to learn one thing.
    changed_identity_accepted: bool = False
    applied: bool = False

    @property
    def feasible(self) -> bool:
        return not (
            self.missing_accounts or self.missing_parties
            or self.missing_documents or self.missing_variants
            or (self.changed_identity and not self.changed_identity_accepted)
        )


def _key_map(session, model, pv_id, key_attr):
    return {
        getattr(row, key_attr): row.id
        for row in session.scalars(select(model).where(model.pack_version_id == pv_id))
    }


def _id_to_key(session, model, pv_id, key_attr):
    return {
        row.id: getattr(row, key_attr)
        for row in session.scalars(select(model).where(model.pack_version_id == pv_id))
    }


def documents_by_ref(session, pv) -> dict[str, dict]:
    """display_ref and doc_type are columns; kind is not -- it lives in the manifest's jsonb,
    so the two sources are joined here rather than in the comparison.

    No longer underscored: `cli.py`'s `packs diff` reads this too, which is a legitimate second
    caller rather than a reason to move it. (Superseded ruling: the earlier plan was to promote
    this and `triage_by_variant` into `version_diff.py`, but that module is pure on purpose -- no
    session, no I/O -- and these two read the database, so moving them there would have destroyed
    the property that makes `version_diff` testable without one.)"""
    kinds = {
        entry["ref"]: entry.get("kind")
        for entry in (pv.manifest or {}).get("documents", [])
    }
    return {
        row.ref: {"display_ref": row.display_ref, "doc_type": row.doc_type,
                  "kind": kinds.get(row.ref)}
        for row in session.scalars(
            select(SourceDocument).where(SourceDocument.pack_version_id == pv.id)
        )
    }


def triage_by_variant(session, pv) -> dict[str, dict[str, bool]]:
    rows = session.execute(
        select(Variant.code, AnswerKeyRow.payload)
        .join(AnswerKeyRow, AnswerKeyRow.variant_id == Variant.id)
        .where(AnswerKeyRow.pack_version_id == pv.id)
    ).all()
    return {code: (payload or {}).get("triage", {}) for code, payload in rows}


def migrate_assignment(
    session: Session, assignment: Assignment, to_version: int, *, dry_run: bool = True,
    actor=None, accept_identity_changes: bool = False,
) -> MigrationReport:
    if assignment.company_policy != "fixed" or assignment.fixed_pack_version_id is None:
        raise MigrationRefused("Only a fixed-company assignment can be migrated.")

    old_pv = session.get(PackVersion, assignment.fixed_pack_version_id)
    to_pv = session.scalars(
        select(PackVersion).where(
            PackVersion.content_pack_id == old_pv.content_pack_id,
            PackVersion.version == to_version,
        )
    ).one_or_none()
    if to_pv is None:
        raise MigrationRefused(f"There is no version {to_version} of this company.")
    if to_pv.version <= old_pv.version:
        raise MigrationRefused("Migrate forward: the target must be a newer version.")

    # Natural-key translation tables, old id -> new id.
    acc_old = _id_to_key(session, Account, old_pv.id, "number")
    acc_new = _key_map(session, Account, to_pv.id, "number")
    par_old = _id_to_key(session, Party, old_pv.id, "code")
    par_new = _key_map(session, Party, to_pv.id, "code")
    doc_old = _id_to_key(session, SourceDocument, old_pv.id, "ref")
    doc_new = _key_map(session, SourceDocument, to_pv.id, "ref")
    var_old = _id_to_key(session, Variant, old_pv.id, "code")
    var_new = _key_map(session, Variant, to_pv.id, "code")

    workspaces = list(
        session.scalars(
            select(Workspace).where(
                Workspace.assignment_id == assignment.id,
                Workspace.pack_version_id == old_pv.id,
                Workspace.archived_at.is_(None),
            )
        )
    )
    ws_ids = [w.id for w in workspaces]
    report = MigrationReport(from_version=old_pv.version, to_version=to_pv.version,
                             workspaces=len(workspaces))
    if not ws_ids:
        # Nothing to remap, but the assignment still has to move: it is what open_workspace reads,
        # so leaving it behind would hand the next student to join the version everyone else has
        # just left. Migrating before anyone has joined is the ordinary case, not an edge one.
        if not dry_run:
            _point_assignment_at(session, assignment, to_pv, actor, 0)
            report.applied = True
        return report

    lines = list(
        session.scalars(select(EntryLine).where(EntryLine.workspace_id.in_(ws_ids)))
    )
    entries = list(
        session.scalars(select(JournalEntry).where(JournalEntry.workspace_id.in_(ws_ids)))
    )
    dispositions = list(
        session.scalars(select(Disposition).where(Disposition.workspace_id.in_(ws_ids)))
    )
    statement_lines = list(
        session.scalars(select(StatementLine).where(StatementLine.workspace_id.in_(ws_ids)))
    )
    report.entry_lines = len(lines)

    # Feasibility: everything a student has actually used must exist in the new version.
    def _missing(used_old_ids, old_map, new_map):
        keys = {old_map[i] for i in used_old_ids if i in old_map}
        return sorted(k for k in keys if k not in new_map)

    used_accounts = {line.account_id for line in lines}
    used_accounts |= {sl.account_id for sl in statement_lines if sl.account_id}
    report.missing_accounts = _missing(used_accounts, acc_old, acc_new)
    report.missing_parties = _missing(
        {line.party_id for line in lines if line.party_id}, par_old, par_new
    )
    used_documents = ({e.document_id for e in entries if e.document_id}
                      | {d.document_id for d in dispositions if d.document_id})
    report.missing_documents = _missing(used_documents, doc_old, doc_new)
    report.missing_variants = _missing({w.variant_id for w in workspaces if w.variant_id},
                                       var_old, var_new)

    # What a ref meant against what it means now, for the refs this student actually used. The
    # checks above ask whether content disappeared; this one asks whether it changed underneath
    # the same name, which is what an envelope-derived rebuild does and what nothing caught.
    used_refs = {doc_old[i] for i in used_documents if i in doc_old}
    report.changed_identity = [
        change for change in identity_changes(
            documents_by_ref(session, old_pv), documents_by_ref(session, to_pv),
            triage_by_variant(session, old_pv), triage_by_variant(session, to_pv),
        )
        if change.ref in used_refs
    ]
    report.changed_identity_accepted = accept_identity_changes

    if dry_run or not report.feasible:
        return report

    # Remap in this one transaction. Deferrable composite FKs let version + id move together.
    def _remap(old_id, old_map, new_map):
        return new_map[old_map[old_id]] if old_id in old_map else None

    for w in workspaces:
        if w.variant_id is not None:
            w.variant_id = _remap(w.variant_id, var_old, var_new) or w.variant_id
        w.pack_version_id = to_pv.id
    for line in lines:
        line.pack_version_id = to_pv.id
        line.account_id = _remap(line.account_id, acc_old, acc_new) or line.account_id
        if line.party_id is not None:
            line.party_id = _remap(line.party_id, par_old, par_new) or line.party_id
    for e in entries:
        e.pack_version_id = to_pv.id
        if e.document_id is not None:
            e.document_id = _remap(e.document_id, doc_old, doc_new) or e.document_id
    for d in dispositions:
        d.pack_version_id = to_pv.id
        if d.document_id is not None:
            d.document_id = _remap(d.document_id, doc_old, doc_new) or d.document_id
    for sl in statement_lines:
        sl.pack_version_id = to_pv.id
        if sl.account_id is not None:
            sl.account_id = _remap(sl.account_id, acc_old, acc_new) or sl.account_id

    if to_pv.first_used_at is None:
        to_pv.first_used_at = old_pv.first_used_at
    # report.changed_identity is non-empty here only if report.feasible let it through, which
    # (since dry_run/not-feasible already returned above) means changed_identity_accepted was
    # True -- the override is what carried this migration. Nothing to pass on the ordinary path.
    _point_assignment_at(session, assignment, to_pv, actor, len(workspaces),
                         accepted_identity=report.changed_identity or None)
    report.applied = True
    return report


#: Caps how many refs an accepted-identity-override migration writes into the audit row. The
#: count is exact regardless; this bounds only the list, so a migration touching hundreds of
#: refs cannot turn one staff action into an unbounded blob.
_MAX_RECORDED_IDENTITY_REFS = 50


def _point_assignment_at(
    session: Session, assignment, to_pv, actor, workspaces: int, *,
    accepted_identity: list[IdentityChange] | None = None,
) -> None:
    """Move the assignment onto the new version and record that it happened.

    Without this the work moves and the assignment does not, which reads as success and leaves
    two quiet faults: the next student to join opens the old version, and a later migration
    looks for workspaces on a version none of them are on any more and finds nothing to do.

    ``accepted_identity``, when given, is the identity changes ``--accept-identity-changes``
    let through: a migration that deliberately reattaches a student's work onto documents whose
    answer changed is exactly the case staff_actions exists for, and until now the only trace of
    that decision was terminal scrollback.
    """
    from_version = session.get(PackVersion, assignment.fixed_pack_version_id).version
    assignment.fixed_pack_version_id = to_pv.id
    session.flush()
    detail = {"from_version": from_version, "to_version": to_pv.version,
              "workspaces": workspaces}
    if accepted_identity:
        refs = sorted({change.ref for change in accepted_identity})
        detail["identity_changes_accepted"] = {
            "count": len(refs), "refs": refs[:_MAX_RECORDED_IDENTITY_REFS],
        }
    staff_actions.record(
        session, actor, "migrate_pack", "assignment", assignment.id, detail=detail,
    )
