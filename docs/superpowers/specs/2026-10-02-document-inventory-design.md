# The online set should contain the documents the envelope contains

**Status:** approved in outline, not yet planned
**Date:** 2 October 2026
**First company:** Alder & Finch Veterinary Clinic

## The request, and what answering it turned up

The ask was to make the online documents look like the printed ones rather than the field-and-value
summaries students see now. Investigating that turned up something larger, and the request cannot
be answered honestly without it.

**The envelope and the online pack do not contain the same documents.**

| | Printed artefacts | Online documents |
| --- | --- | --- |
| Riverbend | **62** | 31 |
| Alder & Finch | **26** | 17 |
| Thorne & Meadow | **68** | not online yet |

The clinic's envelope holds a void cheque, four time cards, two petty cash vouchers, an
appointment request and a price list that the online student never sees. The online student
instead triages a quotation and a boarding enquiry that exist nowhere in the envelope — two
documents authored directly into the pack profile on 1 October.

So a paper student and a screen student are not doing the same set, and the ten triage marks are
awarded for different judgements. Nothing errors, both sides are internally consistent, and no
test can fail — the same shape as every other defect this project has shipped.

## Why this is one piece of work and not two

The online documents are summaries because the pack carries a `text_alternative` — labelled
fields and line items — and no image. The student screen has rendered a zoomable document image
with the text beneath it since it was built; `templates/student/document.html` gates it on
`has_image`, and both packs were generated with `--paper`, so there is nothing to show.

A spike confirmed the pictures are available and good. Extracting one document `<div>` from
`gendocs.py`'s output, rendering it through the same CSS and trimming the whitespace produced a
64 KB clinic sales invoice — teal letterhead, SOLD TO, terms, item table, total, discount note —
and a 35 KB remittance advice with a cheque facsimile, payee in script and a MICR line. Against a
2 MB per-image limit and a 200 MB archive limit, 51 images for the clinic is nothing.

The same spike showed that matching those pictures back to pack documents **cannot be done by
scraping**. Of 17 clinic documents, 7 had no match: some artefacts carry no number, one pack
document covers two printed artefacts, and the two invented distractors have no printed
counterpart at all. The mismatch is not a parsing problem to engineer around. It is the inventory
gap, seen from the other side.

Hence: take the document inventory from the printed set, and the image stops being a feature to
add. It is simply what each document is.

## What gets built

### `gendocs.py` emits a manifest

The paper generator builds each artefact as a self-contained `<div>` and only groups them two or
three to a sheet at the end. It already knows, for each one, what kind it is and — for those that
drive an entry — which transaction it belongs to, because `DOCS` is keyed that way.

It gains an additive output: one HTML file per artefact plus a `manifest.json` naming, for each,
its kind, its printed reference, its date, and its transaction number or `null`. The combined
sheet is unchanged, so the paper set is unaffected.

This is a change to `practicesets`, which the translator spec scoped as paper-only. That scoping
was about not putting an application in a paper repository, not a prohibition on the paper
repository describing its own output. The alternative — a hand-maintained mapping table in the
translator — is two statements of one thing, which is the failure this project has spent its
effort repairing.

### The translator reads the manifest

`scripts/build_pack.py` currently derives one online document per transaction and appends
`NO_ENTRY_DOCUMENTS` from the profile. It will instead take the manifest as the document list:
every printed artefact becomes an online document, with `triage` true where the manifest names the
transaction the artefact is *evidence for* (`entry_for`) and false where it does not. Not `txn`: a
purchase order and its vendor invoice share a transaction and only the invoice is journalised.

Each artefact's `text_alternative` is read off its own HTML rather than built from the transaction
behind it — the transaction cannot distinguish the order from the invoice, and the nine artefacts
that belong to none would carry no text at all. The HTML is also what the photograph shows, so the
picture and the text cannot disagree.

`NO_ENTRY_DOCUMENTS` then disappears from both profiles. The distractors stop being authored and
start being the ones in the envelope.

### The generator ships the pictures

Each manifest entry's HTML renders to a trimmed PNG per variant — **per variant, from that
variant's own HTML**, because the figures printed on the artefact are the whole difference between
the variants and the only reason three exist — shipped in the pack as the `image` the student
screen already knows how to display. The pack's existing MVP Pillow renderer
(`generator/render.py`, "deliberately plain", built-in font) is superseded for these packs.

### The screen puts the document first

`templates/student/document.html` keeps the image as the page and moves "View as text" into a
closed disclosure beneath it. The text remains reachable, which keeps the commitment the template
states — that it is there for everyone, not as a fallback — while removing the summary that
currently competes with the document.

## What this changes about the sets

**Triage becomes a real judgement, and a different one.** The clinic gains a void cheque, four
time cards, two petty cash vouchers, an appointment request and a price list to file. A void
cheque is a better question than a boarding enquiry.

**The answer key grows.** Every new document needs a triage value in every variant. The entries
themselves do not change: the transactions are the same 15.

**One printed document states its own answer.** The clinic's appointment request carries the
footer "Appointment request · no accounting entry". On paper that may be a production marker; on
screen it is the answer printed on the question. It should be reviewed before this ships, not
silently rendered.

## Where this could still be wrong

- **Petty cash vouchers may not be no-entry.** They are numbered 18 and 19, carry accounts and
  amounts, and tie to no transaction. In a set with a replenishment cheque they would support that
  entry; the clinic has none. Whether the paper solution treats them as filed-and-not-entered must
  be read out of the printed solution set, not assumed. The same question applies to time cards
  against the payroll entry.
- **One pack document already covers two printed artefacts.** D13 is "Check 4105 / payroll
  register". Under the manifest those become two documents, which is more faithful but changes
  what a student is asked to connect.
- **Riverbend is live.** Going from 31 to 62 documents is a content change to a pack four versions
  deep with students in it, not a facelift. The clinic was imported yesterday and is the place to
  prove this.

## Sequence

1. The manifest in `gendocs.py`, with the combined sheet proved byte-identical afterwards.
2. The translator reading it, for the clinic only. Compare the resulting document list against the
   printed envelope by hand — 26 against 26.
3. Resolve the vouchers and time cards question against the printed solution set before the triage
   key is written.
4. Images, trimmed, through the existing pack mechanism.
5. The screen change.
6. Riverbend, as its own decision, once the clinic has been worked through a browser.

## Not in this work

- Riverbend and Thorne & Meadow.
- Replacing `generator/render.py`, which stays for packs without printed artefacts.
- The Riverbend item-description divergence, recorded in its profile and still open.
