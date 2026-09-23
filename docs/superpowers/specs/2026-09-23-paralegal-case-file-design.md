# Original Docket — product requirements

**Status:** design, approved in outline, not yet planned
**Product:** Original Docket, a second discipline inside the Original Practice platform
**Date:** 23 September 2026

> **Docketing is the job, not a metaphor.** Entering deadlines into the case calendar is what a
> litigation paralegal is responsible for; firms employ docket clerks and buy docketing systems.
> The deadline calendar a student builds here is a docket. The name is a term of art used
> literally, which is the same thing "books of original entry" does for the accounting set.

---

## 1. What this is

A practice set for paralegal studies, built on the machinery Original Entry already has. A
student receives the file for one lawsuit — pleadings, proofs of service, discovery requests,
correspondence — and must do what a litigation paralegal does with it: work out which documents
start a clock, compute every deadline under the rules, and index the file.

**There is no list of deadlines.** That omission is the design, exactly as the absence of a
transaction list is the design of the accounting set. A student given a deadline list practises
data entry. A student given a proof of service has to notice how service was made, find the rule
that applies, and count — and only then does a date appear.

## 2. Why it ports

Original Entry works because accounting has a right answer. Debits equal credits; the control
account either ties to its subsidiary ledger or it does not. That property is what makes
checkpoints, automatic marking, and the whole "every designed error still balances" pedagogy
possible.

Most paralegal work lacks it. Deadline computation does not.

A response deadline under the Federal Rules is verifiable to the day, and — this is the part
that makes it worth building — **every common error produces a plausible date**:

| Error | What the student sees |
| --- | --- |
| Counting from the document's date rather than the date of service | A date |
| Not adding three days for service by mail | A date |
| Landing on a weekend or court holiday and not rolling forward | A date |
| Counting the trigger day as day one instead of day zero | A date |
| Adding the mail days before the roll-forward instead of after | A date |

Nothing on the calendar tells them which one they have. That is the same teaching moment as a
trial balance that balances and is wrong, and it is why this maps onto the existing marking
model rather than needing a new one.

## 3. The matter

One case, three versions. Working name **Delgado v. Harborview Freight Lines** — a commercial
vehicle collision, chosen because it generates a natural spread of document types without
needing specialist subject knowledge from the student or the instructor.

The file contains roughly twenty-five documents: complaint and summons, proofs of service,
answer, interrogatories, requests for production, requests for admission, a notice of
deposition, a meet-and-confer letter, medical records correspondence, and several documents
that start no clock at all.

**Those last matter most.** Triage is the first thing marked in the accounting set and it will
be the first thing marked here: a courtesy copy, a letter served on somebody else, a document
whose deadline has already run. A student who treats every piece of paper as a trigger has not
understood what a trigger is.

## 4. What the student produces

**Document triage.** For each document: does this start a clock?

**A deadline calendar.** For each document that does, the student records four things:

- the trigger date
- **which rule they applied**
- the method of service
- the resulting date

The second field is not optional and it is the reason this design works. A student who enters
only a date cannot be told apart from one who applied the wrong rule and arrived at the right
answer by luck, nor one who applied the right rule and slipped a day. Capturing the rule makes
the same method-not-match partial credit work that the accounting engine already does. It is the
difference between a grade and feedback.

**An index.** The stack Bates-numbered in order, with date, author, recipient and type.
Sequential numbering with no gaps and no duplicates is machine-checkable and is a real skill.

**A chronology.** What happened when, built from the indexed documents.

**Checkpoints** during the work, in the form the platform already supports: a single date
submitted and confirmed. *When is the answer due?* A student who has the trigger wrong finds out
in the first week rather than at hand-in.

## 5. The rules

Built on the **Federal Rules of Civil Procedure**, with every rule the set depends on reproduced
in the student's booklet — the way the accounting set prints its own accounting policies.

This is deliberate and has three consequences worth stating:

1. The set is portable to any programme, not only those in one state.
2. It is self-contained: the printed sheet is the authority for marking, so an amendment to the
   real rules cannot silently make an answer key wrong.
3. A pack validation rule checks that the text printed in the booklet is the text the engine
   applied. They cannot drift apart.

## 6. Architecture

### 6.1 One new column

`ContentPack.discipline`, defaulting to `"accounting"`. Existing packs are untouched; every
routing decision reads off it.

### 6.2 A pure engine

`originalentry/litigation/`, alongside `ledger/` and `grading/`, with no Flask and no database
imports — the same constraint the existing engines hold to. Date arithmetic is where the bugs
will be, and this makes it exhaustively testable without a database.

Its one important function:

```
compute(trigger_date, rule, service_method, calendar) → Derivation
```

It returns a **worked derivation**, not a date: the trigger, the raw count, the service
extension, the roll-forward, and the result. One decision, three consumers — the answer key is
generated from it, the marking explains where a student diverged, and the instructor solution
shows the working rather than asserting an answer.

The FRCP 6(a) and 6(d) sequence, in order, because the order is itself a trap:

1. Exclude the day of the triggering event.
2. Count forward, calendar or business days as the rule specifies.
3. If the last day is a weekend or court holiday, roll forward to the next day that is neither.
4. If service was by mail, add three days — **then roll forward again.**

### 6.3 Two new tables

`DeadlineEntry` and `IndexEntry`, scoped to a workspace and **superseded rather than mutated** —
the pattern `Disposition` already uses, not the heavier revision machinery `JournalEntry`
carries. A student changing an answer leaves a record.

### 6.4 Reused unchanged

Rosters, enrolment, assignments, workspaces, three versions per student, the savepoint-isolated
write path, activity events, accommodations, reopening, staff marking screens, the audit trail.

Also `Disposition` itself: "does this document need an entry" becomes "does this document start
a clock". Same judgement, same table.

### 6.5 Untouched

`JournalEntry`, `EntryLine`, `PostingRun`, `Account`, `Party`, the ledger engine, every existing
template and route. The accounting product keeps working exactly as it does. This is the whole
argument for adding a discipline beside the existing one rather than generalising the work
models to accommodate both: that refactor would reshape a product with live students in it to
fit a product that does not exist yet, and the abstraction would be drawn around a single
example.

## 7. Pack format

The manifest gains four sections beside the documents it already holds:

- **matter** — caption, court, case number, parties and their counsel
- **court_calendar** — the year's holidays, because a deadline landing on one rolls forward
- **rules** — the FRCP subset: number, printed text, day count, calendar or business days,
  what triggers it, and which service methods extend it
- **service** — on every document: date served, method, who served whom

The answer key holds the expected derivation for each triggering document, the expected index
rows, and the triage decision per document.

## 8. Versions

Two drivers, both on the documents:

- **Shift the service dates.** Every downstream deadline moves, but not uniformly, because a
  shifted date meets weekends and holidays differently. Version B's answers are not version A's
  plus three days, which is what makes versions worth having.
- **Change the service method** on one or two documents, switching the three-day mail extension
  on or off.

## 9. Marking

One hundred marks, mapping one-to-one onto the existing rubric so that the grading framework,
review queue and override machinery work unchanged:

| Part | Marks | Accounting analogue |
| --- | --- | --- |
| Document triage | 10 | Document triage |
| Rule selection | 20 | Journal selection |
| Deadline accuracy | 40 | Entry accounts and amounts |
| Index accuracy | 20 | Posting |
| Chronology | 10 | Subsidiary agreement |

**Method-not-match carries over intact.** A deadline computed correctly from the student's own
wrong trigger date earns the computation marks. This matters more here than in accounting, not
less: one misread service date moves every date after it, and marking line by line against the
key would fail students who understood the work.

Where the engine cannot decide — a student citing a rule the pack does not contain — the run is
flagged for a human, as it is now.

## 10. Validation

Pack rules must check **usability, not only arithmetic.** This is the lesson of the accounting
sets, which passed every validation rule while shipping a document with no amount printed on it,
a remittance advice quoting another company's invoice, and an entire set with no sales invoices
in it. Each was valid. None was workable.

So, for a case file:

- Every document that starts a clock carries its service date and method.
- Every rule the key references is printed in the student's booklet.
- The printed rule text is the text the engine applied.
- No two documents are indistinguishable in the list.
- Every deadline in the key is reproducible by the engine from the document alone.

That last one is the analogue of the derivability audit built for the paper sets, and it is the
closest a machine gets to working the file by hand.

## 11. Testing

- **The engine, exhaustively**: weekend and holiday boundaries, year ends, leap years, and
  specifically the 6(d)-then-6(a) ordering.
- **The key against a hand-computed table** held in the pack source, so that a change to the
  engine cannot quietly move an answer.
- **The validation rules**, each with a pack that violates it.
- **Every screen without JavaScript**, as the existing product requires.

## 12. Non-goals

- No drafting or prose marking. Nothing that needs a human to judge writing quality.
- No privilege log in v1. It has a defensible key and belongs in v2.
- Federal rules only.
- No e-filing, no docketing-system integration.
- **Not legal advice.** A teaching artefact, and the packet says so on its cover.

## 13. Open questions

1. ~~**What is the product called now?**~~ **Settled.** The platform becomes **Original
   Practice**, and the two products sit under it:

   | | Name | Domain |
   | --- | --- | --- |
   | Platform | Original Practice | `originalpractice.com` |
   | Accounting | Original Entry | `originalentry.com` (live) |
   | Paralegal | Original Docket | `originaldocket.com` |

   Nothing is renamed. Original Entry stays as deployed, with students in it. *Practice* carries
   all three senses at once: an accounting practice, a legal practice, and a practice set.

   One known limit: "docket" is US usage. English and Canadian practice say *diary* or
   *limitation dates*. The set is FRCP-based, so it is already a US product, but it forecloses
   an export that was never really open.

2. **Does the paper set come first?** The accounting product exists on paper and in the browser.
   A paper case file could pilot this term and would surface content problems before any code is
   written. Recommended, but it is a scheduling decision.
3. **Who checks the law?** Every figure in the accounting sets can be verified by someone who
   knows accounting. The rules here need a paralegal instructor or an attorney to confirm before
   any of it reaches a student. This is the one dependency that cannot be resolved inside the
   codebase.

## 14. Phasing

1. The pure engine and its tests. No database, no views. It is the whole risk.
2. The pack format, one case file authored, and the validation rules.
3. The `discipline` column, the two tables, and the student screens.
4. Marking components and the staff screens.
5. Checkpoints.

Phase 1 is worth building alone: if the derivation model does not survive contact with real
rules, everything after it changes shape, and nothing has been spent.
