# Concept tagging and the mastery view

**Date:** 19 October 2026 · Spec for the first of four projects taken from the
OpenAccounting Lab PRD (19 October 2026). Revised the same day after a builder review.

## Intent

After an instructor marks a set, Original Entry can say how each student did. It cannot say
**what the class as a whole does not understand**, because nothing in the system knows that
"allowed a discount on an invoice already past its discount period" and "treated an unearned 2%
deduction as a sales discount" are both about cash discounts.

This project gives the app a vocabulary of accounting concepts, attaches that vocabulary to the
two things that already produce evidence, and adds one section to the Diagnostics screen that
reads: *here is what this class is weakest at, and here is who to pull aside.*

### Why this first

Of the four projects, this is the cheapest and the only one the others depend on. The scoring
units and the misconception labels already exist and already carry evidence; what is missing is a
noun that groups them. Doing it first means the short chapter-aligned problems of project two are
born tagged rather than retrofitted.

### What the owner asked for

> add concept tagging … the faculty analytics dashboard

and, from the PRD (§8):

> the dashboard tells an instructor what to reteach, not just the average grade

## Goals

- An instructor can see, per assignment, which concepts the class is weakest at, ranked.
- From a weak concept, reach the students behind it in one click.
- Every figure is derived from marks the app already computes. No new grading.
- The concept vocabulary is one list, the same across every pack, so Riverbend and Ashgrove are
  comparable and so are two instructors' sections.

## Non-goals

- **No new assignment types.** Short chapter-aligned problems are project two.
- **No LMS sync.** Project three.
- **No AI.** The explanations already exist, hand-written, in the error signatures. Generating
  them would be worse and would collide with OpenStax's no-generative-AI term (PRD §9).
- **No cross-assignment or term-to-date mastery.** Per assignment only.
- **No student-facing mastery view.** Staff only.
- **No checkpoint tagging.** Considered and cut: checkpoints are pass/fail rather than scored, so
  there is no natural figure for them, and their keys are pack-local so no migration could seed
  them. Revisit alongside a tagging screen.
- **No tagging screen.** Tags are seeded and revised by migration in v1.
- **No change to how marks are calculated.** Tagging must not move a single student's score.

## Anti-goals

Things that would make this a failure even if it shipped and worked:

- **A number nobody can act on.** "Mastery 71%" with no path to the students or the mistakes is a
  worse version of the average grade.
- **A concept list that drifts per pack.** If Ashgrove calls it "discount timing" and Riverbend
  calls it "early discounts", the comparison the PRD wants is gone and cannot be recovered without
  re-tagging everything.
- **Silent coverage gaps.** If a component with no concept simply vanishes from the view, the
  dashboard looks complete while describing half the assignment.
- **A figure that contradicts the screen it sits on.** The Diagnostics CSV already applies
  per-component grade overrides. Mastery that ignored them would tell a teacher the class is weak
  at something they regraded by hand last week.
- **Retagging that requires touching live student work.** See Constraints.

## Constraints

- **Teachers see their own sections; admins see everything.** This follows the scoped-visibility
  work merged on 7 October 2026. `may_see_section` is the gate, and the new routes must go through
  `_assignment_or_404` like every other console screen that takes an assignment.
- **`abort(404)`, never 403**, consistent with the rest of the console.
- **The CSP forbids inline styles.** `originalentry/security.py:18` is
  `style-src 'self' 'nonce-{nonce}'` with no `unsafe-inline`. No template uses a `style=`
  attribute, and `templates/staff/diagnostics.html` states in its header comment that its bars are
  `<meter>` elements *because* of this. A styled div would render unstyled in production with no
  error.
- **Tailwind v4 emits nothing for a utility it has not scanned**, with no error. Every class used
  must be verified present in `originalentry/static/dist/app.css`, or rebuilt and committed.
- **Pack sources are validated with `extra="forbid"`** (`originalentry/packs/schema.py:25-27`).
  Nothing in this project adds a pack-source field, so no schema change is needed — but a future
  one would require the schema first or import rejects the whole pack.
- **`flask packs import` writes to a shared production database holding real student work.** It is
  not part of this project and must not become a step in routine tagging.
- **Tests run against that same shared Postgres.** The full suite takes about 50 minutes and two
  concurrent runs deadlock. Run the files you are working on.
- **`ruff check originalentry tests` must stay clean** — 6 pre-existing findings in untouched
  files as of `0b23e6f`.

## The two things that already carry evidence

| Artifact | Where it lives | Key space | Carries marks? |
| --- | --- | --- | --- |
| Rubric component | `schema.RubricComponent` on `Pack.rubric` — `key` + `points` | **Global**, ten keys, enumerated in `packs/validate.KNOWN_COMPONENTS` and `grading/components.COMPONENTS` | Yes — `ComponentResult.points` / `.max_points` |
| Error signature | `schema.ErrorSignature` on `AnswerKey` — `key`, `label`, `detect`, `deduct_points` | **Global by key**: `earlydisc` appears in both Riverbend and Alder & Finch and means the same thing | Only when `deduct_points` is set; usually diagnosis only |

Two facts the builder should not have to rediscover:

1. **Error signatures are per-variant.** They sit on `AnswerKey`, so the same signature is
   repeated once per variant — three times in each of Riverbend, Ashgrove and Alder & Finch. This
   is why tags are keyed centrally rather than authored on each copy.
2. **A variant's key may not contain a given signature.** That is why the topic denominator below
   is "students whose variant could have triggered it", not "all students".

## Design

### Concepts are rows, not strings

A `concept` table: `id`, `key` (stable, e.g. `cash_discounts`), `label` (what the dashboard
shows), `group` (`process` | `topic`), `ordinal` (display order *within the drill-down and any
admin listing*; the dashboard list is ranked, not ordinal-ordered), and `retired_at` so a concept
can stop being offered without breaking historical tags.

Seeded by migration with the list below.

### Tags are a central mapping, not a pack field

A `concept_tag` table:

- `concept_id`
- `artifact_kind` — `component` | `signature`
- `artifact_key` — the key as it appears in the pack

Unique on `(artifact_kind, artifact_key)`: one artifact has at most one concept, and one row tags
`earlydisc` everywhere it occurs, which is what makes the cross-pack comparison the PRD wants come
for free.

**Why a table rather than a field in the pack source.** Tagging is metadata about pedagogy, not
content, and it will be revised as the owner learns what the dashboard tells him. A field in the
pack source would make every revision a `flask packs import` against the production database that
holds real student work, to change a label. It would also require authoring each signature's
concept three times, once per variant. The cost is that tags do not travel with a pack to another
institution — see *Known limitations*.

### The concept list

Eighteen, in two groups. Every entry has a real artifact behind it.

**Process — can the student do the mechanics? Measured in marks.**

| Concept | Component key |
| --- | --- |
| Document triage | `triage` |
| Journal selection | `journal_selection` |
| Debit/credit and account classification | `entry_accuracy` |
| Posting to ledgers | `posting_completeness` |
| Subsidiary ledger agrees with control | `subsidiary_agreement` |
| Adjusting entries | `adjustment_form`, `adjustment_amounts` |
| Financial statement preparation | `statements_structure`, `statements_figures` |
| Closing the books | `closing` |

All ten of `KNOWN_COMPONENTS` are tagged, so the "Untagged" row below is genuinely transitional
rather than permanent. Note that `statements_figures` and `statements_structure` appear in no pack
rubric on disk today, and `adjustment_amounts` only in `riverbend-demo`; their concepts exist
ready for the packs that will use them.

**Topic — does the student understand the accounting? Measured in students.**

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
| Depreciation | `depr_on_wrong_doc` |

### Mastery: two measures, both labelled

The two groups cannot share one measure, because signatures carry no marks. Both appear in one
ranked list, and **each row says which measure it is** — the alternative, two separate lists, was
rejected because it forces the "review X next" callout to pick a list.

**Process concepts — share of marks.** For one assignment and one concept:

```
mastery = Σ ComponentMark.points / Σ ComponentMark.max_points
```

over the tagged components of every workspace in the population, pooled across the cohort rather
than averaged per student.

**Marks come from `services/grades.final_marks(session, workspace)`**, not from the raw engine
result — it is "the latest run with every active override applied on top", and it is what the
student marks page, the staff grading pages, `marks_export` and `diagnostics.cohort_csv` all use.
Mastery must agree with the CSV on the same screen.

**Topic concepts — share of students clear.**

```
mastery = students in the population with none of this concept's signatures detected
          ÷ students in the population whose variant's answer key declares at least one of them
```

The denominator excludes students who could not have triggered it, so a signature absent from one
variant does not flatter that variant's students. Rendered the same way, labelled "clear" rather
than "of marks". A concept whose denominator is zero does not appear.

**The population is submitted work.** Workspaces that are not archived and have been submitted.
This matters and an earlier draft of this spec got it wrong: a component's `max_points` is always
the pack's full weight for that component, so an unstarted workspace contributes `0 / full` to
every concept it touches. Including in-progress work would therefore not "degrade gracefully" —
it would drag every percentage toward zero in proportion to how early in the term you looked. The
section header already shows "N of M submitted", so the population is visible on the screen.

**Untagged components appear as a row labelled "Untagged"**, with their pooled share of marks, so
the view never silently omits part of the assignment. The row is not clickable, since the
drill-down is keyed by concept.

### Needs support

Students below a threshold of the assignment's total marks, from `final_marks(...).percent`.
Default **70%**, held in config as `MASTERY_SUPPORT_THRESHOLD` so it can be changed without a
deploy, following the `SCOPED_VISIBILITY` precedent. Counted over the same submitted population
and shown in the section header.

### The screen

A new section on the existing `GET /staff/diagnostics/<assignment>` screen, below what is there
now, because "what happened" and "what do I do about it" belong on one page and that screen
already has a CSV export to extend.

- A context line: section, assignment, N of M submitted, N need support.
- One callout above the list: **Review &lt;weakest concept&gt; before the next assignment.**
  Template text naming the weakest concept, whichever group it comes from. Not prose the owner
  authors per concept.
- A ranked list, weakest first: concept label, a `<meter>` bar, the percentage, and the measure
  ("of marks" / "clear"). Rows below the support threshold are distinguished by the row, not by
  the bar fill, since `<meter>` fill is not ours to colour.
- Each concept row links to the drill-down.

**Drill-down** — `GET /staff/diagnostics/<assignment>/concept/<concept_key>`: the students with
evidence on that concept, their figure for it, and any named misconceptions detected for them,
using the existing error-signature labels verbatim. Scoped identically to its parent.

### Where the code goes

- `originalentry/models/concepts.py` — `Concept`, `ConceptTag`. New module rather than growing
  `content.py`, which already holds the pack side.
- `originalentry/services/mastery.py` — `assignment_mastery(session, assignment) -> MasteryReport`
  and `concept_detail(session, assignment, concept_key)`. The arithmetic lives here, testable
  without a request, as `services/diagnostics.py` already is.
- `originalentry/staff/views.py` — the diagnostics view gains the report; one new route for the
  drill-down.
- `originalentry/templates/staff/diagnostics.html` — the new section.
- One migration, chaining from the current head (`d7f31b905ec4` as of `0b23e6f`), creating both
  tables and seeding the concept list and all component and signature tags above.

### Tests

- `services/mastery.py` unit tests for the arithmetic: process mastery pooled not averaged; topic
  mastery excluding students whose variant lacks the signature; a zero-denominator topic concept
  omitted; untagged components reported rather than dropped; overrides reflected.
- An integration test that a teacher sees mastery for their own section and `404`s on another's,
  and that an admin sees both — the shape of `tests/integration/test_scoped_console.py`.
- Add both routes to the guard matrix in `tests/guards/test_scoping.py`. The drill-down takes an
  `<assignment>`, so `test_every_scoped_console_route_goes_through_one_of_the_two_lookups` will
  require it to use `_assignment_or_404`.
- A guard that every seeded tag resolves: component tags against
  `packs.validate.KNOWN_COMPONENTS`, signature tags against the union of signature keys across
  `packs/*/source.json`. **Not** against imported pack rubrics — three component keys appear in no
  pack on disk, so a guard written against imported rubrics would fail on day one.
- **A test that tagging changes no score.** Grade a workspace, record `final_marks`, add tags,
  grade again, assert the marks are identical. This is the anti-goal made executable.

## Known limitations

- **One list, two measures.** Process rows are a share of marks, topic rows a share of students.
  Each row is labelled, and the section says so once, but it is a genuine compromise taken to keep
  the single ranked list and one callout.
- **Tags do not travel with a pack.** A pack exported to another institution arrives untagged.
  Acceptable while the owner is the only author; the fix, when the shared bank of PRD §9 arrives,
  is an export format that carries tags.
- **Mastery is per assignment only.** A concept weak for six weeks looks the same as one weak
  once. Term-to-date was deferred as roughly double the query and test work for a figure that is
  harder to act on.
- **Choice assignments degrade.** Where `Assignment.company_policy == "choice"`, one cohort spans
  several pack versions and `fixed_pack_version_id` is null. Process mastery still pools correctly
  because component keys are global; topic concepts are reported with their denominators, so a
  concept only one company can trigger is measured only over that company's students. The existing
  triage section of this screen already degrades on choice assignments, and this section degrades
  no worse.
- **Retagging is a migration.** Deliberate for v1. If it becomes frequent, that is the signal to
  build the tagging screen that was cut.
- **Eighteen concepts cover what the current packs test.** Bank reconciliation, inventory costing
  and ratio analysis have no concept because no pack tests them yet.
- **"Needs support" is a mark threshold, not a concept threshold.** It tells you who is
  struggling, not what with. The drill-down is where "what with" lives.

## Left to the builder

- Whether adding a concept later is a further migration or a small admin screen. A migration is
  enough to ship.
- The exact SQL shape of the aggregation — one grouped query or a small number. Correctness and
  not-N+1 are the requirements. `GradeOverride` carries a `superseded_at IS NULL` partial index;
  `final_marks` already encapsulates the join.
- Whether the drill-down is its own template or a block on the diagnostics template.
- Whether the diagnostics CSV export gains mastery columns. Desirable, not required.
- How the measure is labelled in each row, so long as a reader cannot mistake a share of students
  for a share of marks.
