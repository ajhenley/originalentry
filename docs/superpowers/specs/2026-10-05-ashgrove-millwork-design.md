# Ashgrove Millwork — a manufacturing case

**Date:** 5 October 2026

**Deliverable repository:** `practicesets`, not `originalentry`. The case is authored as
`practicesets/companies/ashgrove.py` and built by the existing generators. This spec lives with
the other design documents because `practicesets` keeps no specs directory; the code it describes
does not.

## Intent

Close the one gap the catalog has carried since it began: **no student has ever seen cost flow.**
Alder & Finch sells time, Riverbend and Thorne & Meadow buy finished goods and resell them. None
of the three makes anything.

### What the owner asked for

> other than a product business, I want to create a manufacturing business [...] help me to
> create a small family owned manufacturing business

"Family owned" is load-bearing, not decoration. All three existing cases are corporations with
identical equity blocks — `Common Stock`, `Retained Earnings`, `Dividends`, `Income Summary`. A
family shop is naturally a sole proprietorship, so one case closes two gaps.

## Where it sits

| | Business | Form | Ends at | Time |
| --- | --- | --- | --- | --- |
| Alder & Finch | Service | Corporation | Trial balance | ~2h |
| Riverbend | Merchandiser | Corporation | Unadjusted trial balance | ~5.5h |
| **Ashgrove** | **Manufacturer** | **Sole proprietorship** | **Unadjusted TB + CGM schedule** | **~6h** |
| Thorne & Meadow | Merchandiser | Corporation | Full statements + closing | ~9h |

Set it after Riverbend. Where a syllabus reaches manufacturing rather than the full cycle, it
serves as an alternate to Thorne & Meadow rather than an addition.

## The business

**Ashgrove Millwork** — a custom cabinet and millwork shop, proprietor M. Ashgrove, who works the
bench. Two family members on the payroll: one in the shop, one running the street showroom and
the books. Fourteen working days in December.

The shop builds to order. Each kitchen, built-in or stair rail is a numbered job with a contract
price agreed in advance, and cost is accumulated against it.

## What it teaches that no existing case can

1. **Cost flow.** Raw materials to work in process to finished goods to cost of goods sold. The
   student journalizes every leg, which is the whole of what separates a manufacturer from a
   merchandiser.
2. **"Whose cost is this?"** Job cost sheets form a third subsidiary ledger, controlled by Work in
   Process. This is the catalog's signature question — whose receivable, whose payable — asked on
   new ground. The existing `subsidiary_agreement` grading component marks it unchanged: it
   discovers its ledger kinds from the pack's own accounts and divides its ten marks by however
   many it finds, so three kinds split them three ways automatically.
3. **Proprietorship equity.** `M. Ashgrove, Capital` and `M. Ashgrove, Drawing` in place of common
   stock and dividends. The owner draws from the business, which no student working the other
   three cases ever records.

## Chart of accounts

Riverbend's numbering convention, with the manufacturing and proprietorship blocks replacing
merchandise inventory and the corporate equity accounts.

```
101  Cash                                 201  Accounts Payable
102  Petty Cash                           203  Wages Payable
105  Accounts Receivable                  204  FICA Taxes Payable
106  Allowance for Doubtful Accounts      205  Federal Income Tax Withheld Payable
111  Raw Materials Inventory              206  State Income Tax Withheld Payable
112  Work in Process      [job]           207  Unemployment Taxes Payable
113  Finished Goods Inventory             210  Interest Payable
115  Office Supplies                      215  Customer Deposits on Jobs
116  Prepaid Insurance                    220  Notes Payable
150  Shop Equipment
151  Accum. Depreciation - Shop Equipment 301  M. Ashgrove, Capital
155  Delivery Truck                       302  M. Ashgrove, Drawing
156  Accum. Depreciation - Delivery Truck 399  Income Summary

401  Cabinetry Sales                      501  Cost of Goods Sold
402  Sales Returns and Allowances         505  Factory Overhead
403  Sales Discounts                      506  Factory Wages

511  Showroom Salaries Expense            517  Office Supplies Expense
513  Payroll Tax Expense                  518  Insurance Expense
514  Rent Expense                         521  Bad Debts Expense
515  Advertising Expense                  522  Utilities Expense
516  Delivery Expense                     523  Bank Service Charge Expense
                                          590  Interest Expense
```

`112 Work in Process` carries `subsidiary_kind="job"`. Account `110 Merchandise Inventory` and the
corporate equity accounts do not exist.

**Two clearing accounts carry the design.** `506 Factory Wages` receives the gross payroll and is
emptied by a distribution entry to work in process and factory overhead. `505 Factory Overhead`
accumulates indirect cost and is emptied at period end. Both exist so that the direct/indirect
decision is a *journal entry the student makes*, which is what traps 1, 2 and 5 turn on.

## The cost flow

| Event | Entry |
| --- | --- |
| Lumber and hardware bought | `Raw Materials` dr · `Accounts Payable` cr |
| Direct materials requisitioned to a job | `Work in Process` dr · `Raw Materials` cr |
| Indirect materials requisitioned | `Factory Overhead` dr · `Raw Materials` cr |
| Payroll paid | `Factory Wages` dr · withholdings cr · `Cash` cr |
| Wages distributed | `Work in Process` dr (direct) · `Factory Overhead` dr (indirect shop) · `Showroom Salaries Expense` dr (period) · `Factory Wages` cr |
| Other shop cost incurred | `Factory Overhead` dr · `Cash`/`Accounts Payable` cr |
| Overhead charged to a job | `Work in Process` dr · `Factory Overhead` cr — as each job completes, and to the still-open jobs at period end |
| Job completed | `Finished Goods` dr · `Work in Process` cr — at accumulated cost |
| Job delivered and invoiced | `Accounts Receivable` dr · `Cabinetry Sales` cr, and `Cost of Goods Sold` dr · `Finished Goods` cr |

**Overhead is actual, not a predetermined rate.** It accumulates in `505` and is charged to a job
in proportion to the direct labour hours on its cost sheet. **Charging happens as each job
completes**, not only at period end — otherwise a job transferring to finished goods mid-fortnight
would carry no overhead and `transfer_at_price` would be indistinguishable from a correct entry.
A final entry charges the still-open jobs, leaving `505` nil. Allocating *actual* cost on *actual*
hours produces no variance, so there is no under- or over-applied balance to dispose of — that
belongs to a managerial course, not this one.

### Beginning work in process is zero

The shop finishes every open job before the holiday shutdown, and the set opens on the first
working day after. This is a hard constraint, not flavour, for a reason recorded under **The
schedule** below.

## The job cost sheet ledger

One sheet per job, carrying three columns — direct materials, direct labour, applied overhead —
and controlled by `112 Work in Process`. A sheet is open until its job transfers to finished
goods. The control must equal the sum of the open sheets, exactly as receivables equals the sum of
the customer accounts.

This earns the case its third subsidiary ledger and its fourth checkpoint, and it is what catches
trap 4.

## The five designed traps

**Every designed error leaves the trial balance in balance.** Each entry below is the *wrong* one
and foots internally, so the traps are invisible to footing and visible only by reading individual
accounts. This is the catalog's central design rule and the point to put on the board at the
debrief.

| key | The mistake | Wrong entry | Correct entry |
| --- | --- | --- | --- |
| `indirect_materials` | Glue, abrasives and screws listed on the same requisition as a job's lumber | `Work in Process` dr · `Raw Materials` cr | `Factory Overhead` dr · `Raw Materials` cr |
| `indirect_labour` | Hours spent sharpening blades, sweeping and moving stock, written onto a job time ticket | `Work in Process` dr · `Factory Wages` cr | `Factory Overhead` dr · `Factory Wages` cr |
| `period_cost` | Rent covers the shop and the street showroom; the whole of it charged to the factory | `Factory Overhead` dr (full) · `Cash` cr | `Factory Overhead` dr (shop share) · `Rent Expense` dr (showroom share) · `Cash` cr |
| `transfer_at_price` | A finished job moved to stock at the contract price on the customer's order rather than the cost on its job cost sheet | `Finished Goods` dr (price) · `Work in Process` cr (price) | both legs at accumulated cost |
| `owners_draw` | The proprietor works the bench *and* takes money out; the withdrawal booked as further factory wages | `Factory Wages` dr · `Cash` cr | `M. Ashgrove, Drawing` dr · `Cash` cr |

Four of the five cannot occur in any existing case. `period_cost` is a cousin of Riverbend's
`freight` trap — capitalising something that belongs in expense — by a different mechanism.

Two deserve comment.

**`transfer_at_price` breaks the Work in Process control against the job cost sheets.** The new
subsidiary ledger is what exposes it, so the case's new machinery earns its place rather than
merely existing.

**`owners_draw` is impossible in a corporation**, where an officer's salary genuinely is an
expense. It rests on a point the case must teach explicitly:

> **A sole proprietor is not an employee.** M. Ashgrove works the bench, but the proprietor's own
> labour is never a cost of the business and never reaches a job cost sheet. Money taken out is a
> withdrawal of capital, not wages. The two family members *are* employees, so their hours are
> direct or indirect labour in the ordinary way.

That asymmetry is the lesson, and it is why the shop has two employees besides the owner — without
them there would be no payroll to distribute and no contrast to draw.

The trap also propagates: booked as wages, the draw passes through factory wages into work in
process and inflates every job the distribution entry touches, so one error in the equity section
corrupts product cost. No existing case has a trap that crosses from equity into inventory.

Three of the five — `indirect_materials`, `indirect_labour`, `owners_draw` — corrupt job cost
sheets, which is why the case needs a fourth checkpoint.

## Checkpoints

Cash, the receivables control and the payables control, as the existing cases have, plus **the
Work in Process control** against the sum of the open job cost sheets. Four checkpoints, so a
student can discover a cost-flow error during the work rather than after it.

## Documents

About fifty pages: roughly thirty recordable transactions and three that need no entry at all.

**New document kinds:** production order (authorises a job and states its contract price),
materials requisition, time ticket, and the job cost sheet the student maintains. Alongside them
the familiar set — lumber and hardware invoices, receiving reports, cheques, remittances, the
payroll register, customer contracts carrying deposits, delivery notes.

**The no-entry documents**, where the ten triage marks bite: an estimate for a job the customer has
not yet accepted, a lumber delivery note for stock already invoiced on an earlier document, and a
supplier's statement of account that duplicates invoices already entered.

**Reference documents** (not transactions): the lease schedule showing the shop and showroom
split — without which `period_cost` is unfair — and the shop's hourly rates.

## Journals

Five, as Riverbend has: sales, purchases, cash receipts, cash payments, general. Requisitions,
time tickets and the overhead distribution are general journal entries. No sixth journal: a
manufacturer's distinguishing entries are occasional, and a special journal for them would imply
a volume this shop does not have.

## Variants

Three — A, B and C — on two drivers, following the existing pattern: `P1`, the contract price of
the flagship kitchen, and `QTY`, the board feet of the principal lumber purchase. Both move every
figure downstream.

The combinatorial-variants design (`2026-10-04-combinatorial-variants-design.md`) is a separate,
unstarted project. Ashgrove is authored on the existing three-variant mechanism and would be
migrated with the rest of the catalog if that design is built.

## The schedule, and why the case is a paper set first

The case ends at the unadjusted trial balance **plus a cost of goods manufactured schedule** —
without it, nothing the student has learned about cost flow is ever presented, and a manufacturing
case that produces only a trial balance has no reason to exist.

The schedule the student produces:

```
            ASHGROVE MILLWORK
    Cost of Goods Manufactured Schedule
      For the fortnight ended 31 December

  Direct materials used                  x,xxx
  Direct labour                          x,xxx
  Factory overhead                       x,xxx
    Total manufacturing cost            xx,xxx
  Less work in process, 31 December      (x,xxx)
    Cost of goods manufactured          xx,xxx
```

There is no opening work in process line, for the reason given below.

**The app cannot grade that schedule, and this was verified rather than assumed.** The grading
component `statements_figures` compares each account row against `engine.balances(snapshot,
stage)`, and the engine's entire statement surface is balances at a stage. A cost of goods
manufactured schedule reports *flows* — materials used, labour incurred, overhead charged. Work in
Process's balance is ending work in process, not the cost that passed through it. Splitting work
in process into cost-element accounts does not help, because any such account's balance is still
what remains, not what moved.

A related finding fixes the content: in `statements_figures`,

```python
figures = [row for row in rows if row.kind in (ACCOUNT_ROW, *SUBTOTAL_ROWS)]
share = per_statement / len(figures) if figures else 0.0
```

divides the statement's marks by every figure row, but the loop awards `share` only to account
rows carrying an `account_number` and to subtotals. A labelled figure row with no account — which
is what "beginning work in process" would be — inflates the denominator and earns nothing. **That
is why beginning work in process is zero by design:** with no opening balance the schedule needs
no such row, and the constraint costs nothing because a small shop plausibly finishes its work
before a shutdown.

**Decision: author Ashgrove as a paper set.** This is how the catalog already works — `CASES.md`
records that Riverbend is the only case loaded into the browser app and the other two exist as
paper sets. The schedule is marked from the instructor's key. It also follows the catalog's own
advice, that a packet should be worked by a person before it is set.

The app import is deferred, not abandoned. See **Later** below.

## Marking

The five-part hundred-mark rubric needs no change: document triage 10, journal selection 20, entry
accounts and amounts 40, posting 20, subsidiary agreement 10. The rubric is declared per pack and
`subsidiary_agreement` divides its ten marks by the number of ledger kinds it finds, so a third
ledger costs nothing to mark.

The method-not-match rule applies with particular force here. One misclassified requisition
changes a job cost sheet, the work in process control, the finished goods transfer, cost of goods
sold and the schedule. A student who handled each later step correctly on their own prior figure
has understood the work.

## Out of scope

- **Predetermined overhead rates, under- and over-applied overhead.** Managerial content.
- **Process costing.** This shop builds to order; there is no equivalent-units story to tell.
- **Adjusting entries, financial statements and closing beyond the schedule.** Thorne & Meadow owns
  the full cycle. Ashgrove's `MINI_CLOSE` is the natural home for a proprietorship closing
  appendix — closing the nominal accounts to capital and producing a statement of owner's equity —
  but it is deliberately left for a second pass, so the first version of the case is about cost
  flow and nothing else.
- **Partnership equity.** A second family member admitted as a partner, with capital accounts and
  profit allocation, is Principles II content and a different case.

## Later

Two follow-on projects this case makes concrete, neither part of it:

1. **A flow-aware statement row.** A row kind resolved from `general_ledger` activity over a period
   rather than from a closing balance, with a validation rule and tests. It would let the app grade
   Ashgrove's schedule, and it is also what Thorne & Meadow's statements need — that case has never
   been expressed as a pack either, and probably for the same reason.
2. **A proprietorship mini-close**, once the case has been worked by a person.

## Risks

- **The overhead allocation basis.** Charging actual overhead on actual direct labour hours is
  defensible and variance-free, but the student must see *why* the hours are the basis. Confirm
  while authoring that the job cost sheet makes the proportion legible without arithmetic that
  competes with the accounting.
- **Size.** Thirty transactions over fourteen days with three inventory accounts may exceed six
  hours. Riverbend is twenty-eight transactions in five and a half. Count the student time on the
  first full build and cut jobs, not documents, if it runs long.
- **Trap density on the job cost sheets.** Three of five traps corrupt the same subsidiary ledger.
  Confirm while authoring that a student who falls into all three can still reconcile *something*,
  or the fourth checkpoint becomes discouraging rather than diagnostic.
- **The schedule is not app-graded.** Accepted deliberately. If Ashgrove is imported before the
  flow-aware row exists, the case's distinguishing deliverable is unmarked in the browser, and the
  pack should say so to the instructor rather than silently omit it.
