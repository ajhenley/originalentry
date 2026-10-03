# The online student should not be told what happened

**Status:** approved in outline, not yet planned
**Date:** 2 October 2026
**Packs affected:** Riverbend Bicycle Supply (live), Alder & Finch Veterinary Clinic
**Follows:** the printed-document images work, merged to `pack-figures` as `c22c7ed`

## The finding

`README.md` and `CASES.md` both state the product's defining claim in bold: **there is no
transaction list.** A student reads the documents and works out what happened, "which is the skill
the job actually requires."

Riverbend's online pack gives every student a transaction list. All 31 of its documents carry a
`Description` row in the text a student reads — 93 document/variant pairs — and the row has two
separate sources:

- **84 pairs, 28 documents:** `scripts/build_pack.py` writes `txn["desc"]`, the model's own
  description of the transaction. The comment above the line says the field holds what the document
  is about "in the words on the paper." That was never true: the words are the transaction's, and
  they appear on no document.
- **9 pairs, 3 documents:** `packs/riverbend/profile.py:102,109,118` authors the sentence literally,
  in the `NO_ENTRY_DOCUMENTS` entries for N01, N02 and N03.

The two need different removals, and a change that only deletes the `build_pack.py` line leaves the
three worst ones — the documents whose row states the triage answer — untouched.

For 23 documents the row is redundant. Check 2201 already shows a payee of Meridian Property Trust
and a memo of "December rent"; "Paid December rent" adds nothing.

For eight it gives away the answer. Five of those eight are the set's five designed errors:

| Document | Designed error | What the row tells the student |
| --- | --- | --- |
| D04 | A discount taken past its discount period | "Depot Bikes pays Nov 24 invoice **in full**" |
| D07 | FOB shipping point freight charged to Delivery Expense | "**FOB shipping point**, freight $140 prepaid and added" |
| D18 | A purchase discount credited to revenue | "Paid Norsk inv N-8841 **within 1/15 discount**" |
| D22 | The quantity billed recorded rather than received | "Brightline bills 40 racks; **receiving report shows 38 received**" |
| D23 | An unearned 2% deduction treated as a sales discount | "remits 4,390.40 on a 4,480.00 balance, **deducting 2% outside the discount period**" |

The remaining three are the documents that need no entry, where the row states the reason:
"No order is placed and no goods are requested."

So a screen student cannot fall into the errors the set is built to provoke, and a paper student
can. The two cohorts are not marked on the same thing, in exactly the places the product says its
value lies. Nothing errored, both sides were internally consistent, and no test could fail —
`tests/unit/test_riverbend_pack.py:143` asserted the opposite, that every document carries a
`Description` or it "says nothing about itself".

**Alder & Finch has none of this.** Taking its documents from the printed envelope is what removed
them. The images work fixed this for the clinic as a side effect, which is how it came to light.

## What this work is, and what it is not

This is the first of two steps, and the division is deliberate.

**This step removes what the pack says that the paper does not.** That was the whole of it through
the first round of fixes: it removed hints and changed no figure, no document count, no answer and
no rubric. A student who had already worked twelve documents lost nothing they did.

**Correction, dated 3 October 2026 (fix round 2).** That safety claim is no longer true in its
original, unqualified form, and this is the file the import decision gets read from, so it has to
say plainly what changed. Review found that deleting the `Description` row had gone too far on
three documents: it was also the student's only route to a figure the row happened to carry
correctly, with nothing else in the pack supplying it. Those three document bodies were restored —
figures and rows that are on the paper artefact, never the sentence that states the transaction —
and one of them changed what the document prints.

**D16's `Amount` changed from a fabricated 1,035.00 to the 640.00 the paper artefact shows, and that
old figure had been wrong since this pack was first built**, not introduced by this branch. The
deleted `Description` row was the one place in the pack the correct figure could be read off, via
`_face_amount`'s `sum of debits` fallback landing on 1,035.00 — summing a credit memo's revenue
reversal with its inventory cost reversal, which double-counts exactly the way that fallback's own
docstring warns it can. Removing the row with nothing to replace it would have shipped a document
nobody could journalise correctly; restoring the credit memo's own invoice and item line (what the
paper prints) let `_face_amount` resolve the figure through a new, dedicated branch instead, and
that branch produces the right number. D14 and D23 also gained rows this round — again, rows the
paper prints and the pack had stopped — with no change to either document's figure.

So, in full: **`answers` is byte-identical to before this step for both packs, no document was
added or removed, no checkpoint moved and no rubric moved. One printed figure changed, from a wrong
number to a correct one, on one document.** A student who worked D16 off 1,035.00 before import
could not have reached the key's entry regardless, because 1,035.00 was never the figure this pack's
marking used — `answers` never carried it. After import, D16 reads differently than it did, which
is the one way this step is no longer "changes no figure" in the strict sense: read the corrected
figure as the stronger form of the same safety argument, not a retreat from it. Nobody's existing
*work* is invalidated; the *document* for D16 is.

**The second step migrates Riverbend to the envelope** — 31 summary documents to 62 printed
artefacts with images, as the clinic now is. That changes what a student is marked on and gets its
own spec, reusing `2026-10-02-document-inventory-design.md`, which scoped Riverbend out for exactly
this reason.

Splitting them this way means the marking gap closes now rather than after a second content
migration.

## What gets built

### The transaction's description stops being written onto documents

`scripts/build_pack.py` drops `fields.append(["Description", txn["desc"]])` unconditionally. Not
behind a profile flag and not per company: no pack should put a transaction's description on a
document, and a flag would only let the next company turn the leak back on. That covers 28
documents.

The other three are authored in `packs/riverbend/profile.py`, where the `Description` row is removed
from each `NO_ENTRY_DOCUMENTS` entry and its sentence becomes that document's `FILED_REASONS` value.
The sentence is not rewritten; it moves.

Both removals are needed, and the work is not done when `source.json` merely stops containing
`txn["desc"]`. The check that ends this is that **no document in either pack carries a `Description`
row at all**, which is one assertion over both packs rather than two over one code path.

Verified safe for all 31: no Riverbend document is left with fewer than two informative fields once
the row is gone, and the ones that lean on it most read correctly without it. `Remittance 4861,
Depot Bikes, 6,180.00` is what the paper remittance shows, and finding the trap now requires
looking up what Depot Bikes owed — which is the exercise.

`tests/unit/test_riverbend_pack.py:143` is inverted: no document may carry the transaction's
description. Its present form is the requirement stated backwards, so it cannot be left in place.

### The no-entry reason moves to the answer key

The reason a document needs no entry is the justification for a marked judgement, so it belongs
with the answer and not in the document:

```
AnswerKey.triage_reasons: dict[str, str] = {}
```

Keyed by ref, per version, exactly as `triage` is — so a future set that files a document in one
version only can say why without a special case. Nothing student-facing reads the answer key;
`originalentry/student/views.py` never touches it.

Profiles gain `FILED_REASONS: dict[str, str]`, one sentence per ref, not per version. The builder
writes the same sentence into each version's `triage_reasons` for every ref that version's `triage`
marks as needing no entry. One authored mapping, three identical per-version maps: the profile stays
the single statement of the reason, and the key keeps the shape that lets a future set differ by
version without a new mechanism.

Riverbend's three sentences move there out of `NO_ENTRY_DOCUMENTS`. The clinic's eleven are written
for the first time — its reasons were lost when its inventory moved to the envelope, which is why
`build_walkthrough.py` currently refuses to build its instructor copy at all.

### V17: a marked judgement has to have a stated reason

Two halves, because one is not enough:

- Every document the key marks as needing no entry carries a non-empty reason.
- No reason is recorded for a document that does take an entry.

The second half stops the map rotting as a set changes — a reason left behind on a document that
later takes an entry is how a correct instructor note becomes a wrong one, which is the shape of
the void-cheque defect found in the paper key the same day.

This makes a blank reason impossible for every future pack. The build-time refusal added to
`build_walkthrough.py` in `1a0807c` becomes a thin read of the new field rather than the only thing
standing in the way.

### The clinic's eleven reasons

Checked against the printed solution set: its four completed journals contain no entry traceable to
any of these, and petty cash appears only as the fund's establishment at 150.00 with no
replenishment cheque drawn.

| Documents | Reason |
| --- | --- |
| Purchase orders AF-0440, AF-0441 | An order placed; nothing received and nothing owed yet. The vendor's invoice records the purchase when the goods arrive. |
| Void cheque 4104 | Spoiled and voided before use. No money moved; it is kept so the cheque sequence can be accounted for. |
| Time cards, four | Supporting record for the payroll cheque. The hours reach the books once, through the payroll entry, not card by card. |
| Petty cash vouchers 18, 19 | A disbursement from the petty cash fund. Nothing is journalised until the fund is replenished, and no replenishment cheque is drawn this period. |
| Appointment request AR-3120 | A request to book a future appointment. No service has been given and nothing is owed. |
| Price list | The clinic's own fee schedule. Not a transaction. |

### Both packs regenerate

Riverbend to drop the prose and gain its reasons; the clinic to gain its reasons. Riverbend's
checkpoint figures, expected entries, balances and rubric must come out identical — the only
differences in its `source.json` should be the removed rows and the added key field, and that is an
assertion the work has to make rather than a hope.

`flask packs import` is not part of this work. It writes to a shared live Postgres with students in
it, and the decision to import belongs to the person who knows where those students are.

## What this does not fix

**D22 still leaks after this change.** Without the description it still reads:

```
Quantity billed     40
Quantity received   38
Amount              1,748.00
```

Both figures sit as adjacent labelled rows, and 1,748.00 is 38 × 46.00 — the correct amount,
pre-computed. On paper these are two artefacts, vendor invoice B-3307 and receiving report RR-455,
and the student has to think to compare them. One online document standing in for two printed ones
is the cause, and only the envelope migration fixes it. **Step one must not be reported as having
closed the receiving trap.**

The same applies in smaller measure wherever a profile's `_face_amount` resolves to the figure a
correct student would arrive at rather than the figure the document shows.

## One practical note for whoever builds this

This worktree has no `.venv` of its own, and `pip install` is broken on this machine until
`brew upgrade python@3.14` fixes a `pyexpat` mismatch. Use the main checkout's interpreter —
`/Volumes/Nevvie/Library/Dropbox/habichuela123/originalentry/.venv/bin/python` — which resolves
imports to the current working directory rather than to the checkout it lives in. Confirm that
before trusting a test result:

```
$ <that python> -c "import originalentry; print(originalentry.__file__)"
```

It must print a path inside the worktree you are working in. A venv that resolved to the other
checkout would run every test against the wrong tree and pass.

## Where this could still be wrong

- **Riverbend's documents are text only.** It was built `--paper`, so the text alternative is the
  whole document rather than a transcript of a picture. Removing a row from it removes part of what
  a student has to read, not a duplicate of something they can see. The check that no document falls
  below two informative fields is mechanical; whether each still reads as the artefact it represents
  is a judgement someone should make by reading the 31, not by counting fields.
- **One of the three distractors gets thin, and it is the one that matters.** Measured rather than
  assumed: N01 keeps seven fields and a line item, and N03 keeps five and a line item — both still
  read as the artefact. N02, the request for quotation, drops to `Date`, `Document`, `From`,
  `Reference` and `Amount: None stated`, with no line items. Deciding it needs no entry is then a
  judgement made from an amount that is absent and a reference number, which is thinner than what
  students have had. It is arguably the right thinness — an RFQ really does carry no figures — but
  it is the one to look at before import, and the envelope migration would replace it with a picture
  of the real thing.
- **`FILED_REASONS` is authored text in a profile, and nothing ties it to the printed solution.**
  V17 proves a reason exists, not that it is true. The clinic's eleven were read out of the printed
  solution; nothing stops the next set's being invented.
- **Students mid-course on Riverbend.** This step is designed to be safe for them, but "safe"
  assumes nobody is being marked on a partially-worked set against a key that moves under them. The
  import decision needs that checked.

## Sequence

1. Drop the `Description` row; invert the test that required it. Prove Riverbend's figures, entries,
   balances and rubric are unchanged, and that the only `source.json` differences are the removed
   rows.
2. `triage_reasons` on the answer key, `FILED_REASONS` in both profiles, V17 with both halves, and
   `build_walkthrough.py` reading the new field.
3. Regenerate both packs; validate both; confirm the clinic's instructor copy builds again.
4. Read Riverbend's 31 documents as a student would, and report anything that no longer reads as the
   artefact it represents.
5. Report, and stop. The import is not this work's to make.

## Not in this work

- The envelope migration for Riverbend, which is step two and gets its own spec.
- D22's structural leak, and `_face_amount` resolving to the correct rather than the stated figure.
- Thorne & Meadow, which is not online yet.
- The clinic's two self-answering printed footers (N08, N09), which are a change to the paper
  artefacts in `practicesets` and are being handled separately.
- `flask packs import`.
