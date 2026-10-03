"""What a ref meant, and what it means now.

``flask packs migrate`` refuses when content a student used has disappeared. It cannot see a ref
that still exists and now denotes a different document, which is what an envelope-derived rebuild
produces: the printed set gives the base ref to whichever artefact arrived first, so a transaction's
invoice becomes a sibling and its purchase order inherits the number.

Measured on the two packs in service. Alder & Finch v1 to v2: 17 shared refs, 8 naming a different
artefact, 2 with the triage answer flipped. Riverbend v5 to v6: 31 shared, 18 renamed, 10 flipped,
every one of the ten from needing an entry to needing none.

Pure on purpose: the guard in :mod:`originalentry.packs.migrate` and the operator's report in the
CLI ask the same question, and a question answered in two places is answered two ways eventually.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Compared when both sides carry it. ``kind`` arrived with the printed-envelope packs, so a pack
#: built before it has none, and an absent value is not a change.
_FIELDS = ("display_ref", "doc_type", "kind")


@dataclass(frozen=True)
class IdentityChange:
    ref: str
    field: str
    was: str
    now: str


def identity_changes(
    old_documents: dict[str, dict],
    new_documents: dict[str, dict],
    old_triage: dict[str, dict[str, bool]],
    new_triage: dict[str, dict[str, bool]],
) -> list[IdentityChange]:
    """Every way a ref present in both versions has changed what it denotes.

    Refs added or removed are not reported: they are not identity changes, and a ref a student
    used and lost is already what ``missing_documents`` is for.
    """
    changes: list[IdentityChange] = []
    for ref in set(old_documents) & set(new_documents):
        was, now = old_documents[ref], new_documents[ref]
        for field in _FIELDS:
            before, after = was.get(field), now.get(field)
            if before is None or after is None or before == after:
                continue
            changes.append(IdentityChange(ref, field, str(before), str(after)))

    for code in sorted(set(old_triage) & set(new_triage)):
        before_all, after_all = old_triage[code], new_triage[code]
        for ref in sorted(set(before_all) & set(after_all)):
            if before_all[ref] == after_all[ref]:
                continue
            changes.append(
                IdentityChange(
                    ref, "triage",
                    f"{code}: {'needs an entry' if before_all[ref] else 'needs none'}",
                    f"{code}: {'needs an entry' if after_all[ref] else 'needs none'}",
                )
            )

    return sorted(changes, key=lambda c: (c.ref, c.field, c.was))
