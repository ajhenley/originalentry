# Thorne & Meadow online — the first pack that closes the books

**Status:** approved in outline, not yet planned
**Date:** 1 October 2026
**Company:** Thorne & Meadow Restaurant Supply, Inc.
**Precedes:** the Alder & Finch browser walk-through, which gates this work

## What this is, and what it is not

Two companies serve in Original Entry today and both stop at the unadjusted trial balance. Their
rubrics spend all hundred marks on five grading components; their packs carry `"adjustments": []`
and `"statements": []`.

Thorne & Meadow is a calendar month that ends on 31 December, which is also the year end. Its own
module says the set "does not stop at a trial balance: it **adjusts, states and closes**, and the
student produces an income statement and a balance sheet from books they wrote themselves." It
would be the first production pack to carry the back half of the accounting cycle.

**It is not a platform build.** That needs saying plainly, because the opposite was assumed when
this work was first discussed and it was wrong. The schema, rule V11, the five relevant grading
components, the work models, the routes and the templates are all implemented, and
`tests/golden/test_a3_database.py` and `test_a9_database.py` already drive triage → entries →
adjust → post → close → statements through the real database against a fixture pack, asserting
that `adjustment_form`, `closing` and `statements_structure/figures` score full marks on correct
work. `packs/riverbend-demo/source.json` carries a working adjustment and a working statement
definition in the production format.

What is missing is content. This is an authoring job against a finished machine.

## Where the set ends, decided by reading the booklet

The printed set asks for an income statement and a balance sheet. Week three is "adjusting
entries, statements, closing", the hand-in is "everything, including the statements", and the
instructor is told to expect "questions about which accounts close and in what order".

**No post-closing trial balance is asked for.** So the pack declares two statements, closing is
graded from the student's own closing entries by the `closing` component, and `stage:
"post_closing"` stays unused. The `POST_CLOSING_TYPES` hook in `student/views.py` remains
unexercised, which is the right outcome: a paper student and a screen student should hand in the
same work, and the paper student does not produce one.

## The six adjustments, and why two of them are the interesting ones

Four are fixed by policy and mark themselves:

| Adjustment | Figure | Why it is fixed |
| --- | --- | --- |
| Insurance expired | 2,400 | Half of a 4,800 policy running to 30 June |
| Depreciation, store equipment | 700 | 8,400 a year, straight line, one month |
| Depreciation, delivery van | 620 | 7,440 a year, straight line, one month |
| Interest accrued on the note | 250 | 30,000 at 10%, one month |

Two are not:

| Adjustment | Figure | What it depends on |
| --- | --- | --- |
| Office supplies used | 1,890 | 2,715 charged **as the student posted it**, less 825 counted |
| Estimated uncollectible accounts | 900 | Raising the allowance to 2,500 from **the student's own** balance |

These two are `amount_basis: "dependent"`, and the format has a considered answer for them. The
engine reads the student's own unadjusted balance for the `base_account`, writes the marker a line
— *"Office supplies used: the figure follows from the student's own 115 balance (2,715.00)"* —
and stakes no marks on it. A student who posted supplies differently and then adjusted correctly
from their own figure is not punished for the earlier slip twice.

**The consequence, accepted deliberately: every Thorne & Meadow submission arrives flagged
`needs_review`.** That is a standing claim on whoever marks, and the instructor guide must say so
and name the two figures, so it is expected rather than discovered. `adjustment_amounts` divides
its marks among the four independent adjustments; the two dependent ones are a marker's judgement
by design, not a gap.

## The five traps, chosen not to repeat Riverbend's

`freight` (FOB shipping point freight charged to Delivery Expense), `receiving` (the quantity
billed rather than received), `shortpay` (an unearned 2% deduction treated as a sales discount),
`purchdisc` (a purchase discount credited to revenue), and `deposit` (a January deposit taken as
December revenue).

The last is only possible at a year end, and with the sale invoiced on the thirty-first that had
not shipped it gives the set two cut-off errors — the kind that leave a trial balance in balance
and a result that is wrong. The company's own note makes that the debrief's point: every one of
the five leaves the trial balance balanced.

## The rubric has to be re-cut

A hundred marks currently buy five components. Ten components must share the same hundred, so the
recording half is worth proportionally less than it is in Riverbend — not because recording
matters less, but because this set asks for more. The split is a teaching judgement and belongs in
the plan with a stated rationale, not a silent arithmetic fit.

V15 accepts only known component keys; nothing enforces a total of 100, so the total is a
convention this pack must keep on purpose.

## What is already settled, and is not to be relitigated

- Four journals, as Riverbend: `sales`, `purchases`, `cash_receipts`, `cash_payments`, plus
  `general`. The translator and profile mechanism handle this shape already.
- 42 accounts, including 302 retained earnings and 399 income summary, which `closing` needs; the
  allowance, prepaid insurance and interest payable the adjustments need are all present.
- Adjusting and closing entries are recorded through the existing general-journal screen, whose
  Kind select already offers regular, adjusting and closing. There is no separate closing screen
  and does not need to be one.

## Where this could still be wrong

- **The statements are the untested surface in practice.** `statements_structure` checks section
  order, duplicate accounts and required subtotals against the pack's `allowed_sections`; a chart
  whose `statement_section` values do not line up with the statement definitions produces a pack
  that validates and then marks a correct student down. Riverbend files its revenue accounts under
  `sales_revenue` by convention rather than by thought, and this is the first pack where that
  convention is load-bearing.
- **A balance sheet is a harder statement definition than an income statement**, and the only
  worked example in the repository is an income statement. Its sections, subtotals and the
  `_alternating_net` behaviour of the figures component should be exercised against the real chart
  before the content is authored around it.
- **The rubric re-cut changes Riverbend's marks relative to this set.** Two sets marked out of a
  hundred that measure different things is a comparison an instructor will make anyway.

## Not in this work

- A post-closing trial balance, for the reason above.
- Any change to Riverbend or Alder & Finch.
- The Riverbend item-description divergence, which is recorded in its profile and is a separate
  decision.
- Document images. The clinic shipped `--paper`; so does this.

## Sequence

1. **Work a version of Alder & Finch through the browser as a student.** It is live in the
   catalogue, it is the first three-journal service pack the app has served, and nobody has seen
   its journal picker. If it has a problem, that is worth knowing before a second pack is built on
   the same mechanism.
2. Prove the statement definitions against Thorne & Meadow's real chart — income statement and
   balance sheet — before authoring content around them.
3. The profile and the pre-adjustment content, through the translator, as the clinic went.
4. The six adjustments, the two statements, the rubric re-cut.
5. Validate, import, and work a version through the browser again — this time through adjusting,
   statements and closing.

Step 1 gates the rest. Step 2 is the one that can invalidate the content.
