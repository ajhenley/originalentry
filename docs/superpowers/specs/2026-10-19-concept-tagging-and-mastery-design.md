# Concept tagging and the mastery view

**Date:** 19 October 2026 · Spec for the first of four projects taken from the OpenAccounting Lab
PRD (19 October 2026).

**Revision history.** Draft 1 reviewed by a builder, which found the screen could not be built
from the spec: mastery was defined over components only, while every topic concept attaches only
to signatures. Draft 2 gave topic concepts a percentage. A critical pass on draft 2 found that
percentage **rewarded not doing the work** and was being ranked against an incommensurable
measure. Draft 3, this one, removes it. The two defects and their fix are recorded in
*What earlier drafts got wrong*, because the reasoning is the valuable part.

## Intent

After an instructor marks a set, Original Entry can say how each student did. It cannot say
**what the class as a whole does not understand**, because nothing in the system knows that
"allowed a discount on an invoice already past its discount period" and "treated an unearned 2%
deduction as a sales discount" are both about cash discounts.

This project gives the app a vocabulary of accounting concepts, attaches it to the two things that
already produce evidence, and adds one section to the Diagnostics screen that reads: *here is what
this class is weakest at, here are the mistakes they actually made, and here is who to pull
aside.*

### Why this first

Of the four projects it is the cheapest, and the only one the others depend on. The scoring units
and the misconception labels already exist; what is missing is a noun that groups them. Doing it
first means the short chapter-aligned problems of project two are born tagged rather than
retrofitted.

### What the owner asked for

> add concept tagging … the faculty analytics dashboard

and, from the PRD (§8):

> the dashboard tells an instructor what to reteach, not just the average grade

## Goals

- An instructor can see, per assignment, which concepts the class is weakest at, ranked.
- The named misconceptions the class actually made, with how many students made each.
- From either, reach the students behind it in one click.
- Every figure derived from marks the app already computes. No new grading.
- One concept vocabulary across every pack, so Riverbend and Ashgrove are comparable and so are
  two instructors' sections.

## Non-goals

- **No new assignment types.** Short chapter-aligned problems are project two.
- **No LMS sync.** Project three.
- **No AI.** The explanations already exist, hand-written, in the error signatures. Generating
  them would be worse and would collide with OpenStax's no-generative-AI term (PRD §9).
- **No cross-assignment or term-to-date mastery.** Per assignment only.
- **No student-facing view.** Staff only.
- **No checkpoint tagging.** Cut: checkpoints are pass/fail rather than scored, so there is no
  natural figure, and their keys are pack-local so no migration could seed them.
- **No tagging screen.** Tags are seeded and revised by migration in v1.
- **No percentage for topic concepts.** See *What earlier drafts got wrong* — this one is load
  bearing, not a simplification.

## Anti-goals

Failure even if it ships and works:

- **A number nobody can act on.** "Mastery 71%" with no path to the students or the mistakes is a
  worse version of the average grade.
- **A metric that improves when a student does less.** Draft 2 shipped one. Any figure whose
  denominator is "students who could have made this mistake" must be checked against the student
  who entered nothing at all.
- **Ranking measures that cannot be ordered against each other**, and especially hanging the
  screen's headline advice on that ranking.
- **A concept list that drifts per pack.** If Ashgrove calls it "discount timing" and Riverbend
  "early discounts", the comparison the PRD wants is gone and cannot be recovered without
  re-tagging everything.
- **Silent coverage gaps.** A component with no concept must not vanish from the view.
- **A figure that contradicts the screen it sits on.** The Diagnostics CSV applies per-component
  grade overrides; mastery that ignored them would report the class weak at something the teacher
  regraded by hand last week.
- **Retagging that requires touching live student work.**
- **Changing any student's score.** Enforced structurally, not by a test that cannot fail — see
  *Tests*.

## Constraints

- **Teachers see their own sections; admins see everything**, following the scoped-visibility work
  merged 7 October 2026. `may_see_section` is the gate, and both new routes go through
  `_assignment_or_404` like every other console screen taking an assignment.
- **`abort(404)`, never 403.**
- **The CSP forbids inline styles.** `security.py:18` is `style-src 'self' 'nonce-{nonce}'` with
  no `unsafe-inline`. No template uses a `style=` attribute, and `templates/staff/diagnostics.html`
  states in its header comment that its bars are `<meter>` elements *because* of this. A styled
  div renders unstyled in production with no error.
- **Tailwind v4 emits nothing for a utility it has not scanned**, silently. Every class must be
  verified present in `static/dist/app.css`, or the stylesheet rebuilt and committed.
- **Pack sources are validated `extra="forbid"`** (`packs/schema.py:25-27`). Nothing here adds a
  pack-source field, so no schema change — but a future one needs the schema first.
- **`flask packs import` writes to a shared production database holding real student work.** Not
  part of this project, and must not become a step in routine tagging.
- **Tests run against that same shared Postgres.** The full suite takes ~50 minutes and two
  concurrent runs deadlock.
- **`ruff check originalentry tests` must stay clean** — 6 pre-existing findings in untouched
  files as of `0b23e6f`.

## The two things that already carry evidence

| Artifact | Where it lives | Key space | Carries marks? |
| --- | --- | --- | --- |
| Rubric component | `schema.RubricComponent` on `Pack.rubric` — `key` + `points` | **Global**, ten keys in `packs/validate.KNOWN_COMPONENTS` and `grading/components.COMPONENTS` | Yes — `ComponentResult.points` / `.max_points` |
| Error signature | `schema.ErrorSignature` on `AnswerKey` — `key`, `label`, `detect`, `deduct_points` | **Global by key**: `earlydisc` appears in Riverbend and Alder & Finch meaning the same thing | Only when `deduct_points` is set; usually diagnosis only |

Three facts the builder should not have to rediscover:

1. **Error signatures are per-variant.** They sit on `AnswerKey`, so each is repeated once per
   variant — three times in each of Riverbend, Ashgrove and Alder & Finch. This is why tags are
   keyed centrally rather than authored on each copy.
2. **Signature detection bails on empty books.** `grading/signatures.detect` returns `(), ()` when
   `work.live_entries()` is empty, with a comment explaining that untouched balances would
   otherwise match any signature naming untouched accounts. **Absence of a signature is therefore
   not evidence of understanding.** This is what draft 2 got wrong.
3. **Only five component keys appear in any real pack**: `triage`, `journal_selection`,
   `entry_accuracy`, `posting_completeness`, `subsidiary_agreement`. `adjustment_amounts` appears
   only in `riverbend-demo`. `adjustment_form`, `statements_structure`, `statements_figures` and
   `closing` appear in no pack on disk. See *The five-row reality*.

## Design

### Concepts are rows, not strings

A `concept` table: `id`, `key` (stable, e.g. `cash_discounts`), `label` (what the screen shows),
`group` (`process` | `topic`), `ordinal` (order within an admin listing; the screen ranks rather
than orders), `retired_at` so a concept can stop being offered without breaking historical tags.
Seeded by migration.

### Tags are a central mapping, not a pack field

A `concept_tag` table: `concept_id`, `artifact_kind` (`component` | `signature`), `artifact_key`.
Unique on `(artifact_kind, artifact_key)` — one artifact has at most one concept, and one row tags
`earlydisc` everywhere it occurs, which is what makes the cross-pack comparison come for free.

**Why a table rather than a pack field.** Tagging is metadata about pedagogy, not content, and it
will be revised as the owner learns what the screen tells him. A pack field would make every
revision a `flask packs import` against the production database holding real student work, to
change a label, and would require authoring each signature's concept three times. The cost is that
tags do not travel with an exported pack — see *Known limitations*.

### Two blocks, two measures, never ranked against each other

The screen has two blocks because the two kinds of evidence are not commensurable and must not be
ordered against one another.

**Block A — Mastery by concept.** Process concepts only. Share of marks:

```
mastery = Σ ComponentMark.points / Σ ComponentMark.max_points
```

over the tagged components of every workspace in the population, pooled across the cohort rather
than averaged per student. Ranked weakest first, rendered as a `<meter>` with the percentage.

**Marks come from `services/grades.final_marks(session, workspace)`** — "the latest run with every
active override applied on top" — not the raw engine result. The student marks page, the staff
grading pages, `marks_export` and `diagnostics.cohort_csv` all use it; mastery must agree with the
CSV on the same screen.

**Block B — Most common mistakes.** Topic concepts, as **counts, not percentages**: each detected
signature's label verbatim, the number of students who triggered it, grouped under its concept,
ranked by headcount. A count needs no denominator, which is exactly why it cannot be gamed by a
student doing nothing.

**The population is submitted work.** Workspaces where `grades.submission_status(session,
workspace)` returns `SUBMITTED` or `SUBMITTED_LATE` (`grades.py:23-26`), and `archived_at` is null.
Not `status == "submitted"` and not `submitted_at is not None`, which disagree for reopened work.

This matters for Block A: a component's `max_points` is always the pack's full weight, so an
unstarted workspace contributes `0 / full` to every concept it touches. Including in-progress work
would drag every percentage toward zero in proportion to how early in the term you looked. The
section header shows "N of M submitted" so the population is visible.

**Untagged components appear as a row labelled "Untagged"** in Block A, with their pooled share of
marks, so the view never silently omits part of the assignment. Not clickable, since the drill-down
is keyed by concept.

### The callout

One line above both blocks:

> **Review &lt;weakest process concept&gt; before the next assignment.** The most common mistake
> was &lt;signature label&gt; (N students).

Weakest process concept by share of marks, from Block A. Most common mistake by headcount, from
Block B. Two true statements from two measures, rather than one statement from a ranking that
mixes them. Template text; not prose the owner authors per concept.

### The concept list

Seventeen. Every entry has a real artifact behind it; the **Live** column says whether any pack on
disk actually exercises it today.

**Process — measured in marks (Block A).**

| Concept | Component key(s) | Live |
| --- | --- | --- |
| Document triage | `triage` | yes |
| Journal selection | `journal_selection` | yes |
| Debit/credit and account classification | `entry_accuracy` | yes |
| Posting to ledgers | `posting_completeness` | yes |
| Subsidiary ledger agrees with control | `subsidiary_agreement` | yes |
| Adjusting entries | `adjustment_form`, `adjustment_amounts` | demo pack only |
| Financial statement preparation | `statements_structure`, `statements_figures` | no |
| Closing the books | `closing` | no |

**Topic — counted in students (Block B).** All live; every one of these signatures is in a real
pack.

| Concept | Signature keys |
| --- | --- |
| Unearned revenue and deposits | `deposit` |
| Cash discounts and discount periods | `earlydisc`, `shortpay`, `purchdisc` |
| Contra-revenue versus netting | `refund` |
| Shipping terms and freight | `freight` |
| Goods received versus billed | `receiving` |
| Product versus period cost | `period_cost` |
| Direct versus indirect materials and labour | `indirect_materials`, `indirect_labour` |
| Cost versus selling price on transfer | `transfer_at_price` |
| Owner's withdrawals versus expense | `owners_draw` |

All ten of `KNOWN_COMPONENTS` are tagged, so "Untagged" is transitional rather than permanent. The
three dormant process concepts are seeded so that a pack using those components lights them up
with no migration — they render nothing until then, which the Live column states rather than
implies.

**The vocabulary is the owner's to revise.** It was derived mechanically from existing keys, not
from how he teaches. Changing a label is a one-line migration.

### The five-row reality

Built against the packs as they stand, Block A has **five rows plus Untagged**. There is no
statements row, no closing row, and adjusting entries only on a demo pack. Block B is fully
populated — ten concepts over thirteen signature keys across three real packs.

This is stated plainly because it bears on whether to build now: the half of the screen that is
unique to this product (named misconceptions) is complete, and the half that resembles a
commercial gradebook (ranked mastery bars) is thin until more components are used. A reasonable
reading is that Block B is the reason to ship and Block A grows with the packs.

### Needs support

Students below `SUPPORT_THRESHOLD` of the assignment's total marks, from `final_marks(...).percent`,
over the same submitted population, shown in the section header.

A module constant in `services/mastery.py`, **not** a config flag. 70% is a starting guess to be
revised once a term of real data exists. It is not a kill switch and should not borrow the
`SCOPED_VISIBILITY` pattern, which exists because a misfiring privacy guard locks every teacher out
of every class mid-term.

### The screen

A new section on `GET /staff/diagnostics/<assignment>`, below what is there now, because "what
happened" and "what do I do about it" belong on one page and that screen already has a CSV export
to extend.

- Context line: section, assignment, N of M submitted, N need support.
- The callout.
- Block A: ranked `<meter>` rows, weakest first, label + bar + percentage. Rows below the support
  threshold distinguished on the row, not the bar fill, since `<meter>` fill is not ours to colour.
- Block B: signature label, student count, grouped by concept, ranked by count.
- Rows in both blocks link to the drill-down.

### The drill-down

`GET /staff/diagnostics/<assignment>/concept/<concept_key>`, scoped identically to its parent. Two
shapes, because the two groups carry different evidence:

- **Process concept:** the students in the population with marks on the tagged components — name,
  their points over max for this concept, sorted lowest first, with a link to each student's
  grading page.
- **Topic concept:** grouped by signature, each under its verbatim label, listing the students who
  triggered it. No percentage per student, because triggering a signature is a boolean. Students
  in the population with no signature for this concept are listed last under "none detected", with
  the note that this is not evidence of understanding — the same trap draft 2 fell into, named on
  the screen so a reader does not re-derive it.

### Where the code goes

- `models/concepts.py` — `Concept`, `ConceptTag`. New module rather than growing `content.py`.
- `services/mastery.py` — `assignment_mastery(session, assignment) -> MasteryReport` and
  `concept_detail(session, assignment, concept_key)`. Arithmetic here, testable without a request,
  as `services/diagnostics.py` already is.
- `staff/views.py` — the diagnostics view gains the report; one new route for the drill-down.
- `templates/staff/diagnostics.html` — the new section.
- One migration chaining from the current head (`d7f31b905ec4` as of `0b23e6f`), creating both
  tables and seeding the concepts and all component and signature tags.

### Tests

- **`services/mastery.py` unit tests:** Block A pooled not averaged; overrides reflected;
  untagged components reported rather than dropped; a dormant concept absent rather than 0%;
  **a workspace with no entries contributes nothing to Block B and does not read as mastery** —
  the draft-2 defect, pinned.
- **Population:** a reopened workspace (submitted then reopened) is included, since
  `submission_status` still reports it submitted; an `open` workspace is excluded. These disagree
  under the two rejected definitions, which is the point of the test.
- **Scoping:** a teacher sees their own section and `404`s on another's; an admin sees both — the
  shape of `tests/integration/test_scoped_console.py`.
- **Guard matrix:** add both routes to `tests/guards/test_scoping.py`. The drill-down takes an
  `<assignment>`, so `test_every_scoped_console_route_goes_through_one_of_the_two_lookups` will
  require `_assignment_or_404`.
- **Tag resolution guard:** every seeded component tag's key in `packs.validate.KNOWN_COMPONENTS`;
  every seeded signature tag's key in the union of signature keys across `packs/*/source.json`.
  **Not** against imported pack rubrics — four component keys appear in no pack, so a guard written
  that way fails on day one.
- **Grading isolation, structurally.** Extend `tests/guards/test_import_boundaries.py`, which
  already walks the AST for forbidden imports: nothing under `originalentry/grading/` and nothing
  in `services/grades.py` may import `models.concepts` or `services.mastery`. This replaces the
  draft-2 test that graded, tagged, regraded and asserted the marks were identical — which could
  not fail, because tags live in a table the engine never reads. A guard that can fail beats a
  demonstration that cannot.

## What earlier drafts got wrong

Kept so the reasoning is not lost and the mistakes are not repeated.

1. **Draft 1 could not build its own screen.** Mastery was defined over components; every topic
   concept attached only to signatures; and a concept with no tagged component was specified not to
   appear. The motivating example in the Intent — cash discounts — was therefore unrenderable.
2. **Draft 2's topic percentage rewarded doing less.** "Share of students clear" counted a student
   with no detected signature as clear, and `signatures.detect` returns nothing for empty books. A
   blank submission scored clear on every topic concept; a half-finished one scored clear on
   everything it skipped. The metric improved monotonically as students did less work, and it drove
   the headline callout.
3. **Draft 2 ranked share-of-marks against share-of-students.** They cannot be ordered. The draft
   acknowledged this in Known limitations and ranked them anyway to preserve a single callout,
   choosing a layout convenience over a true number. Worse, the bias was systematic: "zero errors"
   is a harsh bar, so topic rows would almost always sort weakest regardless of what cost the class
   marks.
4. **Draft 2 invented a concept for tidiness.** "Closing the books" was added to cover
   `KNOWN_COMPONENTS` and cannot render, and the draft described three such concepts as "ready for
   the packs that will use them" rather than saying they display nothing.
5. **Draft 2's no-score-change test could not fail**, and draft 2 called it "the anti-goal made
   executable".
6. **Draft 2 borrowed the `SCOPED_VISIBILITY` precedent** to justify a config flag for a support
   threshold, lending a privacy kill switch's reasoning to an arbitrary number.

## Known limitations

- **Block A is five rows today.** See *The five-row reality*.
- **Absence of a signature means nothing.** A student may have misunderstood in a way no signature
  matches, or never reached the document. Block B counts what was detected, never what was not,
  and the drill-down says so where a reader might infer otherwise.
- **Tags do not travel with a pack.** A pack exported elsewhere arrives untagged. Acceptable while
  the owner is the only author; the fix, when the shared bank of PRD §9 arrives, is an export
  format carrying tags.
- **Per assignment only.** A concept weak for six weeks looks like one weak once. Term-to-date was
  deferred as roughly double the query and test work for a figure harder to act on.
- **Choice assignments degrade.** Where `company_policy == "choice"`, one cohort spans several pack
  versions and `fixed_pack_version_id` is null. Block A still pools correctly because component
  keys are global. Block B counts only what each student's own variant could trigger, so a mistake
  possible in one company is counted over that company's students — a count, not a rate, so no
  denominator is misleading. The triage section of this screen already degrades on choice
  assignments and this degrades no worse.
- **Retagging is a migration.** Deliberate for v1; frequent retagging is the signal to build the
  tagging screen that was cut.
- **Seventeen concepts cover what current packs test.** Bank reconciliation, inventory costing and
  ratio analysis have no concept because no pack tests them.
- **"Needs support" is a mark threshold, not a concept threshold.** It says who is struggling, not
  what with. The drill-down is where "what with" lives.

## Left to the builder

- Whether adding a concept later is a further migration or a small admin screen. A migration is
  enough to ship.
- The SQL shape of the Block A aggregation — one grouped query or a few. Correctness and not-N+1
  are the requirements; `final_marks` already encapsulates the override join, which carries a
  `superseded_at IS NULL` partial index.
- Whether the drill-down is its own template or a block on the diagnostics template.
- Whether the diagnostics CSV export gains mastery columns. Desirable, not required.
- Block B's grouping depth: signatures under concept headings, or a flat list with the concept as
  a column. Either is fine so long as a reader can tell which concept a mistake belongs to.
