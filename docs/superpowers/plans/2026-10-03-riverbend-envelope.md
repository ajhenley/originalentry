# Riverbend Envelope Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a migration refuse when a document's ref changes meaning, give the operator a report that shows it beforehand, and rebuild Riverbend's pack from its printed envelope — 31 summary documents becoming 62 photographed artefacts.

**Architecture:** One pure comparison function over two pack versions' documents feeds both the guard inside `migrate_assignment` and a new read-only `flask packs diff` command. Riverbend then moves onto the manifest-driven path that Alder & Finch already uses, which replaces its per-transaction summaries with the envelope's own artefacts and photographs.

**Tech Stack:** Python 3.14, Flask 3.1, Pydantic v2, SQLAlchemy 2.0, pytest, Click (the `flask` CLI). Packs are JSON built by `scripts/build_pack.py` from the read-only sibling repo `../practicesets`. Images render through WeasyPrint → PDF → poppler's `pdftoppm`.

**Spec:** `docs/superpowers/specs/2026-10-03-riverbend-envelope-design.md` — read it before Task 1. It carries the measurements behind every number here and the record of what the live students lose.

## Global Constraints

- **Interpreter:** this worktree has no `.venv`, and `pip install` is broken on this machine (homebrew's `pyexpat` is linked against a newer `libexpat` than macOS ships). Use `/Volumes/Nevvie/Library/Dropbox/habichuela123/originalentry/.venv/bin/python`. Before trusting any test result, confirm `$PY -c "import originalentry; print(originalentry.__file__)"` prints a path containing `originalentry-envelope`.
- Run Python as `$PY -B` and pytest with `-p no:cacheprovider`. Stale bytecode has already made a failing test on this project look like it passed. `pytest-timeout` is NOT installed — never pass `--timeout`.
- Database-backed tests need `DATABASE_URL`. Take it with `export DATABASE_URL="$(grep -m1 '^DATABASE_URL=' /Volumes/Nevvie/Library/Dropbox/habichuela123/originalentry/.env | cut -d= -f2-)"` — do **not** `source` that file, it has an unquoted `<` in `MAIL_FROM` that makes the shell abandon the rest.
- **Do not run the whole suite.** It takes about 34 minutes against a shared Neon Postgres and two concurrent runs have deadlocked. Run the modules you touch; the final task runs it once.
- **Never run `flask packs import`, `flask packs migrate --apply`, `flask grade assignment`, or anything else that writes to the shared live Postgres.** It has three students' work in it. `flask packs validate` and `flask packs diff` are read-only and fine.
- **Never use `git stash`** — the stack is shared with other worktrees and other sessions.
- **Do not modify anything under `../practicesets`.** Riverbend's manifest is already on its `main`; nothing there needs to change.
- Never hand-edit `packs/*/source.json` — regenerate it.
- `ruff check originalentry tests scripts` must be clean at every commit.
- No JavaScript anywhere in this project.
- House style for a refusal: a sentence saying what is wrong and what to do, ending `Nothing was written.`
- **Riverbend is live.** This plan builds version 6; version 5 stays in the catalogue untouched. No task changes v5.

---

## File Structure

| File | Responsibility | Task |
| --- | --- | --- |
| `originalentry/packs/version_diff.py` (new) | one pure function comparing two versions' document identity — no session, no I/O | 1 |
| `tests/unit/test_version_diff.py` (new) | that function, against hand-built inputs | 1 |
| `originalentry/packs/migrate.py` | `changed_identity` on the report, blocking, with an explicit override | 2 |
| `tests/integration/test_pack_migration.py` | the guard refusing, and the override proceeding | 2 |
| `originalentry/cli.py` | `--accept-identity-changes` on `packs migrate`; a new read-only `packs diff` | 2, 3 |
| `tests/integration/test_packs_diff_cli.py` (new) | the report's output | 3 |
| `scripts/build_pack.py` | expand kind-keyed filed reasons to one per ref | 4 |
| `packs/riverbend/profile.py` | reasons by kind, guidance re-keyed to refs, `NO_ENTRY_DOCUMENTS` gone, dead `extra_fields` branches pruned | 4, 5 |
| `packs/riverbend/source.json`, `packs/riverbend/documents/` | regenerated: 62 documents, 186 photographs, version 6 | 5 |
| `tests/unit/test_riverbend_pack.py`, `tests/unit/test_no_transaction_list.py` | updated for 62 envelope-derived documents | 5 |

---

### Task 1: The comparison, as a pure function

**Files:**
- Create: `originalentry/packs/version_diff.py`
- Test: `tests/unit/test_version_diff.py` (new)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  ```python
  @dataclass(frozen=True)
  class IdentityChange:
      ref: str
      field: str          # "display_ref" | "doc_type" | "kind" | "triage"
      was: str
      now: str

  def identity_changes(
      old_documents: dict[str, dict],
      new_documents: dict[str, dict],
      old_triage: dict[str, dict[str, bool]],
      new_triage: dict[str, dict[str, bool]],
  ) -> list[IdentityChange]: ...
  ```
  `*_documents` map a ref to a dict carrying at least `display_ref`, `doc_type` and optionally `kind` — the shape a pack manifest's `documents` entries already have. `*_triage` map a variant code to that variant's `{ref: needs_entry}`. Only refs present in **both** sides are compared; refs added or removed are the caller's business. The result is sorted by `(ref, field)`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_version_diff.py`:

```python
"""A ref is a position, not an identity, and a migration that trusts it reattaches work.

Alder & Finch v1 to v2: of 17 refs shared between the versions, 8 named a different artefact and
2 flipped their triage answer -- D03 went from a vendor invoice, which takes an entry, to a
purchase order, which takes none. The migration would have reported fully feasible, because the
gate asks whether content has disappeared, not whether a surviving ref now means something else.

This is the comparison that answers the second question. It is pure so it can be tested without a
database and reused by both the guard and the operator's report.
"""

from __future__ import annotations

from originalentry.packs.version_diff import IdentityChange, identity_changes


def _docs(**refs):
    return {ref: dict(display_ref=d, doc_type="source_document") for ref, d in refs.items()}


def test_a_ref_that_names_a_different_document_is_reported():
    changes = identity_changes(
        _docs(D01="Invoice 4871"), _docs(D01="Purchase order RB-1180"), {}, {}
    )

    assert changes == [
        IdentityChange("D01", "display_ref", "Invoice 4871", "Purchase order RB-1180")
    ]


def test_an_unchanged_ref_is_not_reported():
    assert identity_changes(_docs(D01="Invoice 4871"), _docs(D01="Invoice 4871"), {}, {}) == []


def test_a_ref_only_one_side_has_is_not_compared():
    """Added and removed refs are real, but they are not identity changes and the existing
    missing_documents check already covers what a student used and lost."""
    assert identity_changes(_docs(D01="A"), _docs(D02="B"), {}, {}) == []


def test_a_changed_doc_type_is_reported():
    old = {"D01": dict(display_ref="Tape", doc_type="source_document")}
    new = {"D01": dict(display_ref="Tape", doc_type="summary")}

    assert identity_changes(old, new, {}, {}) == [
        IdentityChange("D01", "doc_type", "source_document", "summary")
    ]


def test_a_changed_kind_is_reported_and_a_missing_one_is_not():
    """kind arrived with the printed-envelope packs, so a pack that predates it has none. An
    absent kind on either side is not a change -- treating it as one would report every document
    of every older pack."""
    old = {"D01": dict(display_ref="X", doc_type="t", kind="sales_invoice")}
    new = {"D01": dict(display_ref="X", doc_type="t", kind="purchase_order")}
    bare = {"D01": dict(display_ref="X", doc_type="t")}

    assert identity_changes(old, new, {}, {}) == [
        IdentityChange("D01", "kind", "sales_invoice", "purchase_order")
    ]
    assert identity_changes(bare, old, {}, {}) == []
    assert identity_changes(old, bare, {}, {}) == []


def test_a_flipped_triage_answer_is_reported_per_variant():
    """The sharpest case: a document a student correctly journalised becomes one that needs no
    entry, so correct work reads as wrong."""
    docs = _docs(D03="Vendor inv CV-3310")

    changes = identity_changes(
        docs, docs, {"A": {"D03": True}, "B": {"D03": True}}, {"A": {"D03": False}, "B": {"D03": True}}
    )

    assert changes == [IdentityChange("D03", "triage", "A: needs an entry", "A: needs none")]


def test_triage_is_only_compared_where_both_versions_answer_it():
    docs = _docs(D01="X")

    assert identity_changes(docs, docs, {"A": {}}, {"A": {"D01": True}}) == []
    assert identity_changes(docs, docs, {"A": {"D01": True}}, {"B": {"D01": False}}) == []


def test_the_result_is_sorted_so_two_runs_read_the_same():
    old = {"D02": dict(display_ref="a", doc_type="t"), "D01": dict(display_ref="a", doc_type="t")}
    new = {"D02": dict(display_ref="b", doc_type="u"), "D01": dict(display_ref="b", doc_type="t")}

    assert [(c.ref, c.field) for c in identity_changes(old, new, {}, {})] == [
        ("D01", "display_ref"), ("D02", "display_ref"), ("D02", "doc_type")
    ]
```

- [ ] **Step 2: Run it and watch it fail**

```
$PY -B -m pytest tests/unit/test_version_diff.py -q -p no:cacheprovider
```

Expected: collection error, `ModuleNotFoundError: No module named 'originalentry.packs.version_diff'`.

- [ ] **Step 3: Write the module**

Create `originalentry/packs/version_diff.py`:

```python
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
```

- [ ] **Step 4: Run the tests and watch them pass**

```
$PY -B -m pytest tests/unit/test_version_diff.py -q -p no:cacheprovider
```

Expected: 8 passed.

- [ ] **Step 5: Prove each half bites**

Two mutations, each restored afterwards. Record both and their exact failures in your report.

1. Delete `"kind"` from `_FIELDS`. Expected: `test_a_changed_kind_is_reported_and_a_missing_one_is_not` fails and the others pass.
2. Change `if before_all[ref] == after_all[ref]: continue` to `continue` unconditionally. Expected: `test_a_flipped_triage_answer_is_reported_per_variant` fails and the others pass.

If either mutation fails a test it should not, say so rather than adjusting the test.

- [ ] **Step 6: Commit**

```
$PY -B -m ruff check originalentry tests scripts
git add originalentry/packs/version_diff.py tests/unit/test_version_diff.py
git commit
```

Subject: `Ask what a ref meant, not whether it still exists`.

---

### Task 2: The guard inside the migration

**Files:**
- Modify: `originalentry/packs/migrate.py` — `MigrationReport`, its `feasible` property, and `migrate_assignment`
- Modify: `originalentry/cli.py` — the `packs migrate` command (around line 99)
- Test: `tests/integration/test_pack_migration.py` (append)

**Interfaces:**
- Consumes: `identity_changes` and `IdentityChange` from Task 1.
- Produces:
  - `MigrationReport.changed_identity: list[IdentityChange]`, included in `feasible`.
  - `migrate_assignment(session, assignment, to_version, *, dry_run=True, actor=None, accept_identity_changes=False)`. The new keyword suppresses **only** the identity block; `missing_accounts`, `missing_parties`, `missing_documents` and `missing_variants` still refuse regardless.

**How the data is reached.** `display_ref` and `doc_type` are columns on `source_document`; `kind` is **not** a column — it lives in `pack_version.manifest` (jsonb) under `documents`. Triage lives in `answer_key.payload["triage"]`, one row per variant. Build the four inputs for `identity_changes` from those, restricted to the refs the student actually used, which is the same set `missing_documents` is computed from:

```python
used_doc_ids = ({e.document_id for e in entries if e.document_id}
                | {d.document_id for d in dispositions if d.document_id})
used_refs = {doc_old[i] for i in used_doc_ids if i in doc_old}
```

Comparing only used refs keeps the guard about this assignment's data. The whole-pack picture is Task 3's report.

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/test_pack_migration.py`. Read the file's existing `_import` and `_setup` helpers first and use them — do not invent fixtures.

```python
# ── A ref that changes meaning ───────────────────────────────────────────────────────────

def _import_renaming(session, slug, version, ref, display_ref):
    """The same fixture pack, with one document renamed -- the shape an envelope rebuild
    produces, where a ref survives and denotes a different artefact."""
    data = copy.deepcopy(testco_alpha.PACK)
    data["company"]["slug"] = slug
    data["company"]["name"] = slug
    data["version"] = version
    for document in data["documents"]:
        if document["ref"] == ref:
            document["display_ref"] = display_ref
    return import_content(session, schema.load_pack(data), source_sha256=secrets.token_hex(32))


def test_migrate_refused_when_a_used_ref_names_a_different_document(session):
    """The case the gate could not see: nothing is missing, so missing_documents is empty and
    the migration reported feasible while reattaching the student's work."""
    assignment, ws, used_ref = _setup(session, f"ident-{secrets.token_hex(3)}")
    _import_renaming(session, assignment.section.name, 2, used_ref, "Something else entirely")

    report = migrate_assignment(session, assignment, 2)

    assert report.missing_documents == []
    assert [(c.ref, c.field) for c in report.changed_identity] == [(used_ref, "display_ref")]
    assert not report.feasible


def test_the_override_lets_a_deliberate_migration_through(session):
    """A guard with no override makes a considered decision unexecutable, and one that cannot be
    overridden gets deleted by the next person in a hurry."""
    assignment, ws, used_ref = _setup(session, f"ovr-{secrets.token_hex(3)}")
    _import_renaming(session, assignment.section.name, 2, used_ref, "Something else entirely")

    report = migrate_assignment(
        session, assignment, 2, dry_run=False, accept_identity_changes=True
    )

    assert report.applied
    assert report.changed_identity, "the override must still report what it let through"


def test_the_override_does_not_excuse_content_that_is_gone(session):
    """It suppresses the identity block and nothing else."""
    assignment, ws, _ = _setup(session, f"gone-{secrets.token_hex(3)}")
    _import(session, assignment.section.name, 2, drop=USED_ACCOUNT_NUMBER)

    report = migrate_assignment(
        session, assignment, 2, dry_run=False, accept_identity_changes=True
    )

    assert report.missing_accounts == [USED_ACCOUNT_NUMBER]
    assert not report.feasible
    assert not report.applied


def test_an_unchanged_rebuild_reports_no_identity_change(session):
    assignment, ws, _ = _setup(session, f"same-{secrets.token_hex(3)}")
    _import(session, assignment.section.name, 2)

    report = migrate_assignment(session, assignment, 2)

    assert report.changed_identity == []
    assert report.feasible
```

`_setup` currently returns what the existing tests need; if it does not already return the
assignment, the workspace and a ref the student used, extend it to return that triple and update
its existing callers in the same commit. `USED_ACCOUNT_NUMBER` is whichever account number
`test_migrate_refused_when_used_content_is_gone` already drops — reuse that constant rather than
inventing one, and if it is inline there, lift it to a module constant.

- [ ] **Step 2: Run them and watch them fail**

```
export DATABASE_URL="$(grep -m1 '^DATABASE_URL=' /Volumes/Nevvie/Library/Dropbox/habichuela123/originalentry/.env | cut -d= -f2-)"
$PY -B -m pytest tests/integration/test_pack_migration.py -q -p no:cacheprovider
```

Expected: the three new identity tests fail on `AttributeError: 'MigrationReport' object has no attribute 'changed_identity'` or on the unexpected keyword, and the existing six still pass.

- [ ] **Step 3: Add the field and fold it into feasibility**

In `originalentry/packs/migrate.py`:

```python
from .version_diff import IdentityChange, identity_changes
```

In `MigrationReport`, beside the other lists:

```python
    #: Refs the student used that denote a different document in the new version. Empty is the
    #: ordinary case; non-empty means their work would be reattached, which no amount of remapping
    #: fixes because the document it referred to is not there under that name any more.
    changed_identity: list[IdentityChange] = field(default_factory=list)
```

and in `feasible`:

```python
    @property
    def feasible(self) -> bool:
        return not (
            self.missing_accounts or self.missing_parties
            or self.missing_documents or self.missing_variants
            or self.changed_identity
        )
```

- [ ] **Step 4: Compute it**

Give `migrate_assignment` the new keyword:

```python
def migrate_assignment(
    session: Session, assignment: Assignment, to_version: int, *, dry_run: bool = True,
    actor=None, accept_identity_changes: bool = False,
) -> MigrationReport:
```

After `report.missing_variants` is assigned and before the `if dry_run or not report.feasible:`
line, add:

```python
    # What a ref meant against what it means now, for the refs this student actually used. The
    # checks above ask whether content disappeared; this one asks whether it changed underneath
    # the same name, which is what an envelope-derived rebuild does and what nothing caught.
    used_refs = {doc_old[i] for i in used_documents if i in doc_old}
    report.changed_identity = [
        change for change in identity_changes(
            _documents_by_ref(session, old_pv), _documents_by_ref(session, to_pv),
            _triage_by_variant(session, old_pv), _triage_by_variant(session, to_pv),
        )
        if change.ref in used_refs
    ]
    if accept_identity_changes:
        accepted, report.changed_identity_accepted = report.changed_identity, True
        report.changed_identity = []
        report.accepted_identity_changes = accepted
```

Hoist the used-document set so both this and `missing_documents` read it:

```python
    used_documents = ({e.document_id for e in entries if e.document_id}
                      | {d.document_id for d in dispositions if d.document_id})
    report.missing_documents = _missing(used_documents, doc_old, doc_new)
```

Add two helpers beside `_key_map`:

```python
def _documents_by_ref(session, pv) -> dict[str, dict]:
    """display_ref and doc_type are columns; kind is not -- it lives in the manifest's jsonb,
    so the two sources are joined here rather than in the comparison."""
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


def _triage_by_variant(session, pv) -> dict[str, dict[str, bool]]:
    rows = session.execute(
        select(Variant.code, AnswerKeyRow.payload)
        .join(AnswerKeyRow, AnswerKeyRow.variant_id == Variant.id)
        .where(AnswerKeyRow.pack_version_id == pv.id)
    ).all()
    return {code: (payload or {}).get("triage", {}) for code, payload in rows}
```

`migrate.py` does not currently import the answer-key model. Add it to the existing
`from ..models import (...)` block as:

```python
from ..models import AnswerKey as AnswerKeyRow
```

The class is `AnswerKey` in `originalentry/models/content.py` (table `answer_key`). `migrate.py`
imports no `schema`, so there is no live collision — the alias is for the reader, because
`schema.AnswerKey` is the pydantic model elsewhere in this package and the two are easy to confuse
in a file that deals in both versions' rows.

Add the two report fields the override sets:

```python
    #: Set when --accept-identity-changes was given: what the override let through, kept so the
    #: refusal's reason survives in the record even though it no longer blocks.
    accepted_identity_changes: list[IdentityChange] = field(default_factory=list)
    changed_identity_accepted: bool = False
```

- [ ] **Step 5: Run the tests and watch them pass**

```
$PY -B -m pytest tests/integration/test_pack_migration.py -q -p no:cacheprovider
```

Expected: all pass, the existing six included.

- [ ] **Step 6: Wire the CLI**

In `originalentry/cli.py`'s `packs_migrate`, add the option and pass it through:

```python
    @click.option("--accept-identity-changes", "accept_identity", is_flag=True,
                  help="Proceed even though refs the student used now name different documents. "
                       "Their recorded work will be reattached. Read `flask packs diff` first.")
```

```python
            report = migrate_assignment(
                db.session, assignment, to_version, dry_run=not apply_it, actor=None,
                accept_identity_changes=accept_identity,
            )
```

and print what was refused or accepted, beside the existing `missing …` lines:

```python
        for change in report.changed_identity:
            click.echo(f"  {change.ref} {change.field}: {change.was} -> {change.now}", err=True)
        for change in report.accepted_identity_changes:
            click.echo(f"  accepted: {change.ref} {change.field}: {change.was} -> {change.now}")
```

The existing `if not report.feasible:` block already rolls back and raises; leave it.

- [ ] **Step 7: Prove the guard bites**

Change `or self.changed_identity` back out of `feasible` and run
`tests/integration/test_pack_migration.py`. Expected:
`test_migrate_refused_when_a_used_ref_names_a_different_document` fails on `assert not
report.feasible`. Restore it. Then remove `if change.ref in used_refs` and confirm
`test_an_unchanged_rebuild_reports_no_identity_change` still passes while the fixture's other
documents do not leak in — if it fails, the filter is load-bearing and say so.

- [ ] **Step 8: Commit**

```
$PY -B -m ruff check originalentry tests scripts
git add originalentry/packs/migrate.py originalentry/cli.py tests/integration/test_pack_migration.py
git commit
```

Subject: `Refuse a migration that would reattach a student's work`.

---

### Task 3: `flask packs diff`, so the operator sees it first

**Files:**
- Modify: `originalentry/cli.py` — a new `packs` subcommand beside `validate` (around line 141)
- Test: `tests/integration/test_packs_diff_cli.py` (new)

**Interfaces:**
- Consumes: `identity_changes` from Task 1.
- Produces: `flask packs diff --company SLUG --from N --to M`, read-only, exit 0 always. Reports, over **all** shared refs rather than only a student's: refs added, refs removed, and every identity change. Where Task 2's guard protects one assignment's data, this answers "what would this version do to anybody".

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_packs_diff_cli.py`:

```python
"""What a new version would do to the refs students hold, before it is imported anywhere.

The clinic's v1-to-v2 rebuild renamed 8 of 17 shared refs and flipped 2 triage answers, and
nothing said so until someone went looking afterwards. This is the looking, made cheap.
"""

from __future__ import annotations

import copy
import secrets

import pytest
from originalentry.packs import schema
from originalentry.packs.importer import import_content

from tests.packs import testco_alpha

pytestmark = pytest.mark.db


def _import(session, slug, version, rename=None):
    data = copy.deepcopy(testco_alpha.PACK)
    data["company"]["slug"] = slug
    data["company"]["name"] = slug
    data["version"] = version
    if rename:
        ref, display_ref = rename
        for document in data["documents"]:
            if document["ref"] == ref:
                document["display_ref"] = display_ref
    return import_content(session, schema.load_pack(data), source_sha256=secrets.token_hex(32))


def test_the_report_names_a_ref_that_changed_meaning(session, app):
    slug = f"diff-{secrets.token_hex(3)}"
    first = _import(session, slug, 1)
    ref = first.documents[0].ref if hasattr(first, "documents") else "INV-1"
    _import(session, slug, 2, rename=(ref, "A different artefact"))
    session.commit()

    result = app.test_cli_runner().invoke(
        args=["packs", "diff", "--company", slug, "--from", "1", "--to", "2"]
    )

    assert result.exit_code == 0, result.output
    assert ref in result.output
    assert "A different artefact" in result.output


def test_an_identical_rebuild_reports_nothing_changed(session, app):
    slug = f"same-{secrets.token_hex(3)}"
    _import(session, slug, 1)
    _import(session, slug, 2)
    session.commit()

    result = app.test_cli_runner().invoke(
        args=["packs", "diff", "--company", slug, "--from", "1", "--to", "2"]
    )

    assert result.exit_code == 0, result.output
    assert "no document changed what it denotes" in result.output


def test_a_version_that_is_not_there_is_refused_with_a_sentence(session, app):
    slug = f"absent-{secrets.token_hex(3)}"
    _import(session, slug, 1)
    session.commit()

    result = app.test_cli_runner().invoke(
        args=["packs", "diff", "--company", slug, "--from", "1", "--to", "9"]
    )

    assert result.exit_code != 0
    assert "version 9" in result.output
```

If this module's `session`/`app` fixture names differ from the rest of `tests/integration/`, follow
whatever that directory's `conftest.py` provides rather than these names.

- [ ] **Step 2: Run it and watch it fail**

```
$PY -B -m pytest tests/integration/test_packs_diff_cli.py -q -p no:cacheprovider
```

Expected: every test fails, with Click reporting `No such command 'diff'`.

- [ ] **Step 3: Add the command**

In `originalentry/cli.py`, beside `packs_validate`:

```python
    @packs.command("diff")
    @click.option("--company", "slug", required=True, help="Company slug, e.g. riverbend.")
    @click.option("--from", "from_version", type=int, required=True)
    @click.option("--to", "to_version", type=int, required=True)
    def packs_diff(slug: str, from_version: int, to_version: int) -> None:
        """What a migration between two versions would do to the refs students hold.

        Read-only. `flask packs migrate` refuses when a ref a student used changed meaning; this
        shows the whole picture before anyone is migrated, including refs nobody has touched yet.
        """
        from sqlalchemy import select as _select

        from .models import ContentPack, PackVersion
        from .packs.migrate import _documents_by_ref, _triage_by_variant
        from .packs.version_diff import identity_changes

        pack = db.session.scalars(
            _select(ContentPack).where(ContentPack.slug == slug)
        ).one_or_none()
        if pack is None:
            raise click.ClickException(f"No company {slug!r} in the catalogue.")

        def _version(n: int) -> PackVersion:
            pv = db.session.scalars(
                _select(PackVersion).where(PackVersion.content_pack_id == pack.id,
                                           PackVersion.version == n)
            ).one_or_none()
            if pv is None:
                raise click.ClickException(f"{slug} has no version {n} in the catalogue.")
            return pv

        old_pv, new_pv = _version(from_version), _version(to_version)
        old_docs, new_docs = _documents_by_ref(db.session, old_pv), _documents_by_ref(db.session, new_pv)

        added = sorted(set(new_docs) - set(old_docs))
        removed = sorted(set(old_docs) - set(new_docs))
        changes = identity_changes(
            old_docs, new_docs,
            _triage_by_variant(db.session, old_pv), _triage_by_variant(db.session, new_pv),
        )

        click.echo(f"{slug} v{from_version} -> v{to_version}: "
                   f"{len(old_docs)} documents -> {len(new_docs)}")
        if added:
            click.echo(f"  added ({len(added)}): {', '.join(added)}")
        if removed:
            click.echo(f"  removed ({len(removed)}): {', '.join(removed)}")
        if not changes:
            click.echo("  no document changed what it denotes")
            return
        flipped = [c for c in changes if c.field == "triage"]
        click.echo(f"  changed meaning: {len({c.ref for c in changes})} ref(s), "
                   f"{len(flipped)} with a flipped triage answer")
        for change in changes:
            click.echo(f"    {change.ref} {change.field}: {change.was} -> {change.now}")
```

Importing two underscore-prefixed helpers from `migrate` is deliberate: the alternative is a
second way of reading the same two shapes, and this file already reaches into modules this way for
`migrate`. If a reviewer objects, the fix is to move `_documents_by_ref` and `_triage_by_variant`
into `version_diff` as public functions and import them from there — do that rather than
duplicating them.

- [ ] **Step 4: Run the tests and watch them pass**

```
$PY -B -m pytest tests/integration/test_packs_diff_cli.py -q -p no:cacheprovider
```

Expected: 3 passed.

- [ ] **Step 5: Prove it bites, and that it writes nothing**

Mutation: make `identity_changes` be called with `new_docs, new_docs`. Expected:
`test_the_report_names_a_ref_that_changed_meaning` fails because the output reports nothing
changed. Restore.

Then confirm the command is read-only: run it against the two fixture versions and assert, in a
scratch check rather than a committed test, that `db.session.dirty` and `db.session.new` are both
empty afterwards. Report what you saw.

- [ ] **Step 6: Commit**

```
$PY -B -m ruff check originalentry tests scripts
git add originalentry/cli.py tests/integration/test_packs_diff_cli.py
git commit
```

Subject: `Show what a version would do before it does it`.

---

### Task 4: Reasons by kind, and Riverbend's profile on the manifest path

**Files:**
- Modify: `scripts/build_pack.py` — `_triage_reasons`
- Modify: `packs/riverbend/profile.py` — `FILED_REASONS`, `GUIDANCE`, `GUIDED_SEQUENCES`
- Test: `tests/unit/test_triage_reasons.py` (append)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `FILED_REASONS` may map **either** a document ref **or** a document kind to a sentence. `_triage_reasons(profile, triage, manifest=None)` gains the manifest so it can resolve a ref's kind; a ref-keyed entry always wins over a kind-keyed one. Riverbend's `GUIDANCE` and `GUIDED_SEQUENCES` become ref-keyed.

Riverbend has 34 filed documents across **nine kinds** — 6 customer purchase orders, 5 bills of
lading, 5 purchase orders, 4 receiving reports, 6 time cards, 5 petty cash vouchers, a void cheque,
a request for quotation and a price list. Thirty-four near-identical strings is a worse artefact
than nine with a mechanism, and V17 still needs one reason per ref, so the builder expands.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_triage_reasons.py`:

```python
# ── Reasons authored by kind ─────────────────────────────────────────────────────────────

def _profile_with(filed_reasons):
    class P:
        FILED_REASONS = filed_reasons
    return P()


def _bp():
    import importlib.util
    spec = importlib.util.spec_from_file_location("build_pack", ROOT / "scripts" / "build_pack.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MANIFEST = [
    {"ref": "N01", "kind": "time_card"},
    {"ref": "N02", "kind": "time_card"},
    {"ref": "N03", "kind": "price_list"},
    {"ref": "D01", "kind": "cheque"},
]
TRIAGE = {"N01": False, "N02": False, "N03": False, "D01": True}


def test_a_reason_keyed_by_kind_reaches_every_document_of_that_kind():
    """Riverbend files 34 documents of nine kinds. Authoring 34 sentences would be nine
    sentences and twenty-five copies of them."""
    reasons = _bp()._triage_reasons(
        _profile_with({"time_card": "Supporting record for the payroll cheque."}),
        TRIAGE, manifest=MANIFEST,
    )

    assert reasons == {"N01": "Supporting record for the payroll cheque.",
                       "N02": "Supporting record for the payroll cheque."}


def test_a_reason_keyed_by_ref_wins_over_its_kind():
    """One document of a kind sometimes needs its own sentence; the specific beats the general."""
    reasons = _bp()._triage_reasons(
        _profile_with({"time_card": "The general one.", "N02": "This one is different."}),
        TRIAGE, manifest=MANIFEST,
    )

    assert reasons["N01"] == "The general one."
    assert reasons["N02"] == "This one is different."


def test_a_kind_reason_never_reaches_a_document_that_takes_an_entry():
    """V17 forbids a reason on a document that needs an entry, so the expansion must respect
    triage rather than paint every document of a kind."""
    reasons = _bp()._triage_reasons(
        _profile_with({"cheque": "Should not appear."}), TRIAGE, manifest=MANIFEST,
    )

    assert reasons == {}


def test_without_a_manifest_only_ref_keys_resolve():
    """Riverbend's own pack built before this change, and the clinic's, pass no manifest here."""
    reasons = _bp()._triage_reasons(
        _profile_with({"time_card": "By kind.", "N03": "By ref."}), TRIAGE,
    )

    assert reasons == {"N03": "By ref."}
```

`ROOT` is already defined at the top of this module; if it is not, define it the way the file's
other helpers locate the repository root.

- [ ] **Step 2: Run them and watch them fail**

```
$PY -B -m pytest tests/unit/test_triage_reasons.py -q -p no:cacheprovider -k kind
```

Expected: failures on the unexpected `manifest` keyword, and on kind keys resolving to nothing.

- [ ] **Step 3: Teach the builder kinds**

Replace `_triage_reasons` in `scripts/build_pack.py`:

```python
def _triage_reasons(profile, triage: dict[str, bool], manifest=None) -> dict[str, str]:
    """One authored sentence per filed document, from a mapping keyed by ref or by kind.

    Riverbend files 34 documents of nine kinds and the clinic eleven of nine; by-ref authoring is
    right for the clinic and would be twenty-five copies for Riverbend. A ref key beats a kind key
    so one document of a kind can say something of its own.

    A ref that is filed and resolves to no sentence is absent from the result rather than defaulted
    to "": V17 then reports it against the pack by name, where a silent "" would make an
    incomplete pack valid.
    """
    authored = getattr(profile, "FILED_REASONS", {})
    kind_of = {entry["ref"]: entry.get("kind") for entry in (manifest or [])}
    reasons = {}
    for ref, needs_entry in triage.items():
        if needs_entry:
            continue
        sentence = authored.get(ref) or authored.get(kind_of.get(ref))
        if sentence:
            reasons[ref] = sentence
    return reasons
```

Then pass the manifest at the manifest-arm call site:

```python
                "triage_reasons": _triage_reasons(profile, triage, manifest=manifest),
```

Leave the Riverbend-arm call site as it is — it has no manifest, and that arm is retired in Task 5.

- [ ] **Step 4: Run them and watch them pass**

```
$PY -B -m pytest tests/unit/test_triage_reasons.py tests/unit/test_alderfinch_pack.py -q -p no:cacheprovider
```

Expected: all pass. The clinic's pack must be unaffected — its `FILED_REASONS` is ref-keyed, so the
kind lookup never fires for it.

- [ ] **Step 5: Author Riverbend's nine sentences and re-key its guidance**

In `packs/riverbend/profile.py`, replace `FILED_REASONS` with the nine, keyed by kind:

```python
# Why each filed document needs no entry, authored by kind: the envelope files 34 documents and
# they are nine kinds, so nine sentences and a mechanism beat thirty-four strings. V17 still
# requires one reason per document; scripts/build_pack.py expands kind to ref.
FILED_REASONS = {
    "customer_po": "The customer's own order. Nothing has been shipped or invoiced against it "
                   "yet, so there is nothing to record; the invoice does that.",
    "purchase_order": "Our order to a supplier. Nothing has arrived and nothing is owed; the "
                      "vendor's invoice records the purchase when the goods do.",
    "bill_of_lading": "The carrier's receipt for goods leaving the warehouse. It evidences the "
                      "shipment behind an invoice, and the invoice is what is recorded.",
    "receiving_report": "What the warehouse counted on arrival. It is the check against the "
                        "vendor's invoice, not an entry of its own.",
    "time_card": "Supporting record for the payroll cheque. The hours reach the books once, "
                 "through the payroll entry, not card by card.",
    "petty_cash_voucher": "A disbursement from the petty cash fund. Nothing is journalised until "
                          "the fund is replenished.",
    "void_cheque": "Spoiled and voided before use. No money moved; it is kept so the cheque "
                   "sequence can be accounted for.",
    "request_for_quote": "An enquiry about terms. No order is placed and no goods are requested.",
    "price_list": "A supplier's price notice. Nothing has been ordered against it.",
}
```

Re-key the guidance from transaction numbers to refs. It is `{1, 2}` today because the
per-transaction arm knows nothing about refs; the manifest arm needs refs, and transaction 2 is now
three artefacts. The guidance goes on the document the student must act on:

```python
# Keyed by ref, as the manifest arm requires. Transaction 2 is three artefacts in the envelope --
# D02 the customer's purchase order, D02-2 the invoice, D02-3 the bill of lading -- and the
# scaffolding belongs on the invoice, which is the one that takes an entry. V10 caps guided
# documents at two.
GUIDED_SEQUENCES = {"D01", "D02-2"}
```

`GUIDANCE` keeps its text and changes its keys to `"D01"` and `"D02-2"`. Read the two existing
entries and move them across verbatim — do not reword them.

- [ ] **Step 6: Check the profile still self-checks, then commit**

```
$PY -B -m pytest tests/unit/test_profile_checks.py tests/unit/test_triage_reasons.py -q -p no:cacheprovider
$PY -B -m ruff check originalentry tests scripts
git add scripts/build_pack.py packs/riverbend/profile.py tests/unit/test_triage_reasons.py
git commit
```

Subject: `Author a filed reason once per kind, not once per document`.

`test_profile_checks.py` may fail here because Riverbend's `check()` validates `GUIDANCE` keys
against transactions. If so, that check is now wrong about the world — update it to validate refs
against the manifest the way the clinic's does, in this commit, and say so in your report.

---

### Task 5: Riverbend's pack, rebuilt from the envelope at version 6

**Files:**
- Modify: `packs/riverbend/profile.py` — delete `NO_ENTRY_DOCUMENTS`, prune dead `extra_fields` branches and their `check()` cross-checks
- Regenerate: `packs/riverbend/source.json`, `packs/riverbend/documents/`
- Modify: `tests/unit/test_riverbend_pack.py`, `tests/unit/test_no_transaction_list.py`

**Interfaces:**
- Consumes: kind-keyed `FILED_REASONS` and ref-keyed guidance from Task 4.
- Produces: `packs/riverbend/source.json` at version 6, 62 documents, 186 photographs under `packs/riverbend/documents/{A,B,C}/`.

**Regenerating.** The envelope comes from the read-only practicesets checkout — do not modify it:

```
for CODE in A B C; do
  PRACTICESET_COMPANY=riverbend PRACTICESET_OUT=/tmp/rb-env/$CODE \
    $PY generators/gendocs.py $CODE
done
```
run with `cwd=/Volumes/Nevvie/Library/Dropbox/habichuela123/practicesets`. Then:

```
$PY -B scripts/build_pack.py riverbend --version 6 --documents /tmp/rb-env > packs/riverbend/source.json
```

That renders 186 PNGs and takes several minutes. **Version 5's committed pack is what is in
service; this replaces the file on disk with version 6.** If you need v5 to compare against, read
it with `git show HEAD:packs/riverbend/source.json` rather than keeping a copy around.

- [ ] **Step 1: Write the failing tests**

In `tests/unit/test_riverbend_pack.py`, the module asserts things true of a 31-document
per-transaction pack. Add the envelope expectations; do not delete the figure assertions, which
must still hold:

```python
def test_the_pack_holds_every_printed_artefact(generated):
    """31 summary documents became 62 printed ones: the envelope's own artefacts, not one
    document per transaction. 28 evidence a transaction and 34 need no entry, so filing is the
    majority judgement rather than a token three."""
    pack = schema.load_pack(generated.pack)

    assert len(pack.documents) == 62
    triage = generated.keys["A"]["triage"]
    assert sum(triage.values()) == 28
    assert len(triage) - sum(triage.values()) == 34


def test_every_filed_document_has_a_reason(generated):
    """V17 requires one per document; Task 4 authors nine by kind and the builder expands."""
    for code, key in generated.keys.items():
        for ref, needs_entry in key["triage"].items():
            if not needs_entry:
                assert key["triage_reasons"].get(ref, "").strip(), f"{code}: {ref}"


def test_the_receiving_trap_is_two_documents_again(generated):
    """D22 printed Amount 1,748.00 -- the received quantity priced out, which is the answer --
    above a line reading 1,840.00. In the envelope the invoice bills 1,840.00 and a separate
    receiving report records 38 received, so comparing them is the student's work."""
    pack = schema.load_pack(generated.pack)
    text = {d.ref: json.dumps(d.variants["A"].text_alternative.model_dump()) for d in pack.documents}

    assert "1,840.00" in text["D22-2"]
    assert "1,748.00" not in " ".join(text.values())
    assert "38" in text["D22-3"]
```

In `tests/unit/test_no_transaction_list.py`, Riverbend now has no `Description` row by
construction rather than by removal — its text comes off the artefact. The existing
`test_no_document_carries_a_description_row[riverbend]` and the designed-error test must still
pass; check them rather than assuming, because the phrases they look for came from the summary
text that no longer exists. If a phrase can no longer appear by construction, say so in your
report and leave the assertion in place: a test that cannot fail because the defect is impossible
is different from one that cannot fail because it is badly written, and this file's docstring
should say which it is.

- [ ] **Step 2: Run them and watch them fail**

```
$PY -B -m pytest tests/unit/test_riverbend_pack.py -q -p no:cacheprovider
```

Expected: the three new tests fail on `assert 31 == 62` and on missing refs.

- [ ] **Step 3: Take `NO_ENTRY_DOCUMENTS` out of the profile**

Delete the whole `NO_ENTRY_DOCUMENTS` list from `packs/riverbend/profile.py`. Its three authored
distractors are replaced by the envelope's 34 filed artefacts. The three sentences it carried now
live in `FILED_REASONS` by kind — the request for quotation and the price list keep theirs, and
the purchase order's is the `purchase_order` sentence.

- [ ] **Step 4: Regenerate the pack**

Run the two commands under **Regenerating** above. Expected: 62 documents, 186 PNGs,
`"version": 6`.

- [ ] **Step 5: Run the tests and watch them pass**

```
$PY -B -m pytest tests/unit/test_riverbend_pack.py tests/unit/test_no_transaction_list.py \
    tests/unit/test_triage_reasons.py tests/unit/test_pack_reproducible.py -q -p no:cacheprovider
```

`test_pack_reproducible` rebuilds Riverbend with the committed pack's own declared version, so it
needs the envelope too — it currently calls `build_source(company, PRACTICESETS, version=...)` with
no `documents_dir`, which would now rebuild a 31-document pack and fail against a 62-document one.
The signature is `build_source(company, practicesets, slug=None, documents_dir=None,
images_dir=None, version=1)`, so pass it by keyword:

```python
    return module.build_source(
        company, PRACTICESETS, documents_dir=_envelope(), version=version
    )
```

Produce the envelope the way `tests/unit/test_document_manifest.py`'s `envelope` fixture does —
`gendocs.py` per version into a `tmp_path_factory` directory — rather than inventing a new
mechanism, and make it module-scoped so three versions are generated once. If the practice sets are
absent it must fail with a sentence rather than skip, which is what `_require_sets` in that file
already does and why.

- [ ] **Step 6: Prune what the summary path needed**

`extra_fields` in `packs/riverbend/profile.py` carries a `Terms` row on the five sales invoices,
the remittance arithmetic for transactions 14 and 23, and D16's returned item — every one added
because the **summary** text could not be journalised without it. The artefact prints its own
figures now, so each is redundant at best and a second diverging statement of the same number at
worst.

Check each against the regenerated pack before deleting it: find the figure in the document's text
and confirm it arrives from the artefact. Delete the branch only when you have seen that, and
delete the matching cross-check in `profile.check()` with it. Report each one and what you saw. If
a figure turns out to arrive **only** from `extra_fields`, keep that branch and say which.

- [ ] **Step 7: Validate and commit**

```
$PY -B scripts/generate_pack.py packs/riverbend/source.json /tmp/riverbend-v6.zip
DATABASE_URL=sqlite:////tmp/throwaway.db FLASK_APP=originalentry.app:create_app \
  $PY -B -m flask packs validate /tmp/riverbend-v6.zip
$PY -B -m ruff check originalentry tests scripts
git add packs/riverbend/profile.py packs/riverbend/source.json packs/riverbend/documents \
        tests/unit/test_riverbend_pack.py tests/unit/test_no_transaction_list.py \
        tests/unit/test_pack_reproducible.py
git commit
```

Expected: `Valid.` reporting 3 variants and 186 images. Subject:
`Give Riverbend the documents its envelope prints`.

---

### Task 6: The gate

**Files:** none. This task changes nothing and produces a report.

- [ ] **Step 1: Validate and re-validate reproducibility**

Rebuild the pack a second time from a fresh envelope and confirm `source.json` and all 186 PNGs
come out byte-identical. The clinic's 78 were identical across three rebuilds; if Riverbend's are
not, that is a finding and the renderer is not deterministic at this size.

- [ ] **Step 2: Read the 62 documents**

For each document, in each of the three versions, hold it against its own expected entry and ask
the standard `_text_alternative`'s docstring states: does it carry **everything a student needs to
journalise it** and **nothing that tells them how**? Report by ref anything that fails either half.
The clinic's equivalent reading found two Criticals, so this is not a formality. Pay particular
attention to the five designed errors — the freight on D07, the discount past its period on D04,
the quantity billed on D22, the purchase discount on D18, the unearned 2% on D23 — and say for
each whether a student could now reach it from the documents and whether anything announces it.

- [ ] **Step 3: Run the full suite, once**

```
export DATABASE_URL="$(grep -m1 '^DATABASE_URL=' /Volumes/Nevvie/Library/Dropbox/habichuela123/originalentry/.env | cut -d= -f2-)"
$PY -B -m pytest tests/ -p no:cacheprovider
```

About 34 minutes. Nothing else may touch the database while it runs. Report the count and any
failure in full.

- [ ] **Step 4: Report, and stop before production**

The remaining steps write to a shared live Postgres with three students' work in it and are **not
this plan's to run**. Set them out for the controller with the version numbers filled in:

```
flask grade assignment zkqr808bg1                       # bank their marks FIRST
flask export marks zkqr808bg1 --out marks-v5.csv
flask packs import /tmp/riverbend-v6.zip
flask packs diff --company riverbend --from 5 --to 6     # read this
flask packs migrate --assignment zkqr808bg1 --to-version 6
flask packs migrate --assignment zkqr808bg1 --to-version 6 --apply --accept-identity-changes
```

Grading must precede the migration: afterwards their entries sit on documents that need no entry
and the grade would be computed against a key their work no longer matches. Report the validate
result, the suite result and your reading of the 62, and stop.

---

## Self-Review

**Spec coverage.** Part 0 (bank the marks) is Task 6 Step 4, as a runbook rather than an executed
step, because it writes to production. Part 1's guard is Tasks 1–2 and its report is Task 3. Part 2
is Tasks 4–5: the 62 documents, the 28/34 split, reasons by kind, `NO_ENTRY_DOCUMENTS` gone, the
guidance re-keyed, D22 verified. Part 3 is Task 6 Step 4. The spec's three open risks are covered:
the dead `extra_fields` branches are Task 5 Step 6, the 186-render determinism is Task 6 Step 1,
and the unworked 62-document screen is Task 6 Step 2. **One spec item has no task on purpose:**
re-cutting the rubric, which the spec names as an open question rather than work.

**Placeholders.** Two deliberate soft spots, both with instructions rather than silence: the
integration fixture names in Task 3 Step 1 (follow `tests/integration/conftest.py` if they differ)
and `_setup`'s return shape in Task 2 Step 1 (extend it and update its callers). Both are "match
what is there", not "decide something".

**Type consistency.** `identity_changes(old_documents, new_documents, old_triage, new_triage)` and
`IdentityChange(ref, field, was, now)` are used identically in Tasks 1, 2 and 3.
`_documents_by_ref(session, pv)` and `_triage_by_variant(session, pv)` are defined in Task 2 and
imported in Task 3, which Task 3 flags as the one import a reviewer may want moved — with the
remedy named rather than left open. `_triage_reasons(profile, triage, manifest=None)` keeps its
first two parameters positional so the untouched Riverbend-arm call site still works.

**One risk the plan carries knowingly.** Task 5 replaces Riverbend's committed pack with version 6
while version 5 is the one in service. Nothing reads the working tree in production, so this is
safe, but a reviewer looking at the diff sees a live pack's content change wholesale. Task 5's
preamble says so, and Task 6 Step 4 keeps every production command out of the plan's hands.
