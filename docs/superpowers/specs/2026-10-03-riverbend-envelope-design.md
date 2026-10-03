# Riverbend from its printed envelope, and the identity a document keeps

**Status:** approved in outline, not yet planned
**Date:** 3 October 2026
**Pack:** Riverbend Bicycle Supply — live, one assignment, three students
**Reuses:** `2026-10-02-document-inventory-design.md`, which proved this path on Alder & Finch and
scoped Riverbend out "as its own decision"

## The finding that reshaped this work

The job began as "give Riverbend the same treatment the clinic got": take the document inventory
from the printed envelope, 31 summary documents becoming 62 printed artefacts with photographs.
Investigating it turned up something the clinic's migration had already walked past.

**A document's `ref` is a position, not an identity, and the migration gate checks the wrong
thing.** `flask packs migrate` refuses when content a student used has *disappeared*
(`missing_documents`). It cannot see a ref that still exists and now means a different document.

Measured, not supposed:

| | refs shared between versions | naming a different artefact | triage answer flipped |
| --- | --- | --- | --- |
| Alder & Finch v1 → v2 | 17 | **8** | **2** (D03, D11) |
| Riverbend v5 → v6 | 31 | **18** | **10** |

Riverbend's ten are D02, D03, D05, D07, D09, D11, D13, D19, D22 and D28, every one of them from
"needs an entry" to "needs none".

The clinic's migration would have reported fully feasible. D03 went from "Vendor inv CV-3310",
which takes an entry, to "Purchase order AF-0440", which takes none — so a student's correct
journal entry would have been reattached to a document whose right answer is "file it". The clinic
escaped only because no assignment was ever created on it.

Riverbend is worse because the envelope orders each transaction's artefacts by arrival, so the
customer's purchase order takes the base ref and the invoice becomes the sibling:

```
D02   Invoice 4871        (entered)  ->  customer PO CC-7741      (filed)
D03   Vendor inv N-8841   (entered)  ->  purchase order RB-1180   (filed)
D22   Vendor inv B-3307 / RR-455     ->  purchase order RB-1183
N01   Purchase order RV-2210         ->  void cheque 2207
```

`migrate.py` remaps by ref (`migrate.py:153,178,182`), so every disposition and entry line follows
its label onto whatever that label now denotes.

## What this work is, in four parts

### Part 0 — bank the three students' marks before anything moves

The live assignment `zkqr808bg1` holds 3 workspaces, 68 triage decisions and 189 entry lines, about
three quarters through. **The decision has been taken to migrate it and accept that their recorded
work is misattached**; this part exists so that what their work *earned* survives even though the
work's correspondence to the key does not.

```
flask grade assignment zkqr808bg1
flask export marks zkqr808bg1 --out marks-zkqr808bg1-v5.csv
```

Grading has to happen **before** the migration, because afterwards their entries sit on documents
that need no entry and the grade would be computed against a key their work no longer matches. The
CSV is the record. Keep it outside the repository.

This is not a safeguard against the decision, and it does not reverse it. It is the one thing that
costs nothing and preserves the outcome.

### Part 1 — a ref must not change meaning, and the operator must be able to see when it does

Two additions, and they are the reusable half of this work:

**The guard, in `packs/migrate.py`.** For every ref present in both versions, compare the
artefact's identity and refuse when it changed:

- `display_ref` and `doc_type` from `source_document`
- `kind` from the pack version's manifest (there is no `kind` column; it lives in the jsonb)
- the triage answer, per variant, from the answer key

`MigrationReport` gains the changed refs the way it already carries `missing_documents`, and
`feasible` goes false. The existing CLI already prints those lists and already refuses on
infeasible, so the plumbing exists.

**The guard is overridable, loudly.** `--accept-identity-changes` proceeds anyway, naming every
changed ref on the way through. Part 3 needs it: this migration is going ahead with its eighteen
changed refs by deliberate decision, and a guard with no override would make that decision
unexecutable rather than considered. A guard that cannot be overridden gets deleted by the next
person in a hurry; one that must be spelled out gets read.

**The report, a new `flask packs diff`.** Given a company and two versions, print what a migration
would do to identity: refs added, removed, renamed, and triage answers flipped. It writes nothing.
It is what should have been run before the clinic's import and before this one.

### Part 2 — Riverbend's 62 documents

The clinic's path, unchanged, applied to Riverbend. `gendocs.py` already emits Riverbend's manifest
on `practicesets/main`; nothing in that repository needs to change.

- `scripts/build_pack.py riverbend --documents <envelope> --version 6`, which takes the inventory
  from the manifest and photographs each artefact.
- **62 artefacts: 28 evidencing a transaction, 34 needing none.** Triage goes from 28 entered /
  3 filed to 28 / 34, so filing becomes the majority judgement rather than a token three. That is a
  different and better exercise, and it is a content change, not a facelift.
- 31 refs are new: 19 suffixed siblings (`D02-2`, `D02-3`, …) and 12 in the `N04`–`N15` series.
- **186 photographs** (62 × 3 versions) against the clinic's 78. The clinic's archive was 5,094 KB,
  so expect roughly 12 MB — comfortably inside V16's 200 MB and V12's 2 MB per image, but 2.4× the
  render time.
- `NO_ENTRY_DOCUMENTS` disappears from `packs/riverbend/profile.py`, as it did from the clinic's.
- `FILED_REASONS` must cover all 34 filed refs, which V17 requires. They are not 34 distinct
  sentences: the 34 are 6 customer purchase orders, 5 bills of lading, 5 purchase orders,
  4 receiving reports, 6 time cards, 5 petty cash vouchers, a void cheque, a request for quotation
  and a price list — **nine kinds**. Author by kind with a per-ref override, and have the builder
  expand kind to ref so V17 still sees one reason per document. Thirty-four near-identical strings
  is a worse artefact than nine with a mechanism.

**The guidance has to be re-keyed, and that is a judgement.** Riverbend's `GUIDANCE` and
`GUIDED_SEQUENCES` are keyed by **transaction number** — `{1, 2}` — because the per-transaction arm
knows nothing about refs. The clinic's are keyed by ref, which is what the manifest arm requires.
Transaction 2 is now three artefacts: `D02` the customer's purchase order, `D02-2` the invoice,
`D02-3` the bill of lading. The guidance belongs on the document the student has to act on, so it
goes to `D02-2`, with transaction 1's going to `D01`; the purchase order and the bill of lading are
filed and need no scaffolding. V10 caps guided documents at two, so the count is unchanged. Written
down because it was not obvious and nothing in the pack would have caught putting it on the wrong
one of the three.

**D22 is fixed by this, and it was checked rather than assumed.** In the envelope the vendor invoice
prints `40 … 1,840.00, Total 1,840.00` and a separate receiving report prints `40 … 38`. The
fabricated `1,748.00` — the received quantity priced out, which is the answer — disappears, because
the document's text comes off the artefact instead of from `_face_amount`. Comparing the two is the
student's work again.

### Part 3 — import, look, migrate

```
flask packs validate riverbend-v6.zip
flask packs import riverbend-v6.zip
flask packs diff --company riverbend --from 5 --to 6      # read this
flask packs migrate --assignment zkqr808bg1 --to-version 6              # refuses
flask packs migrate --assignment zkqr808bg1 --to-version 6 --apply --accept-identity-changes
```

The diff report will name eighteen changed refs and ten flipped answers. Running the migration
anyway is the decision taken, and the override is how a decision gets expressed rather than
smuggled.

## What the three students will see

Said plainly, because whoever marks them needs to know and it will not be visible from the marks:

Their 68 triage decisions and 189 entry lines keep their refs and lose their documents. Ten
documents they correctly journalised become documents that need no entry, so their correct work
reads as wrong. Their three filed judgements land on a void cheque and two time cards. **None of
this is their error**, and the marks exported in Part 0 are the only record of what they actually
earned.

## Where this could still be wrong

- **The work I did last week to patch the summary path may now be dead code.** `extra_fields` in
  Riverbend's profile carries a `Terms` row on the five sales invoices and the remittance arithmetic
  for D14 and D23, and D16's returned item — all added because the summary text could not be
  journalised without them. Under the envelope path the artefact prints its own figures, so those
  branches are redundant at best and a second, diverging statement of the same numbers at worst.
  Check each against the artefact before deleting it; `profile.check()`'s literal cross-checks go
  with whatever goes.
- **The rubric may need re-cutting.** Triage is a tenth of the marks over 31 documents today; over
  62, with 34 of them filed, the same marks buy a different judgement. Nobody has decided whether
  that is a re-weighting or a deliberate change in emphasis.
- **186 renders is 2.4× anything this pipeline has done.** The clinic's 78 were deterministic and
  byte-identical across three rebuilds, so the method holds; the render time and the archive size
  are what to watch.
- **Nobody has worked a 62-document set through a browser.** The clinic's 26 have not been worked
  either. A triage list of 62 with 34 filings is a different screen from 31 with 3.
- **The guard compares what the database holds, not what the pack meant.** A pack that renamed a
  document's `display_ref` for cosmetic reasons would trip it. That is the right direction to fail,
  but it will produce a false alarm eventually, and the override is how that gets handled.

## Not in this work

- Thorne & Meadow, which is not online at all.
- Re-cutting the rubric; it is named above as an open question, not a task here.
- Deriving refs from the artefact so identity cannot drift by construction. It is the principled
  fix and it was considered and set aside: it renumbers a pack that is imported and live, to prevent
  a hazard the Part 1 guard detects completely.
- Any change to the clinic, whose v2 is in service and correct.
