# Short chapter-aligned problems

**Date:** 20 October 2026 · The second of four projects taken from the OpenAccounting Lab PRD
(19 October 2026). The first, concept tagging and the mastery view, merged at `96753dd`.

**Revision history.** Draft 1 was reviewed by a builder, which found it silently reversed three
standing architectural commitments without naming any of them, and that its central claim about
concept tagging was false as designed. Draft 2, this one, settles both and the staff-side scope
draft 1 never budgeted for. The findings are kept in *What draft 1 got wrong*.

## Intent

Original Entry does one thing extremely well: a student keeps one company's books for a term, and
the app grades the whole cycle with a real ledger engine and names the misconceptions it finds.
That is a practice-set product. It is not a homework product.

What an instructor sets weekly is eight or ten short problems tied to the chapter they just
taught — *"On 5 October the business bought equipment for $4,800, paying $1,800 cash and agreeing
to pay the rest later. Record the entry."* That is what WileyPLUS and Connect sell, behind a paid
access code, and it is the gap the PRD exists to close.

This project adds that shape **without building a second product**. A chapter problem set is a
small pack, so the ledger engine, partial credit, the error signatures, marks export and section
scoping all work unchanged.

### What the owner decided

A chapter problem set is one assignment, living in the pack model. Students get a new
single-problem screen, work any problem as often as they like, and the best N count. Feedback says
more each time. Authoring is a hand-written file imported by a CLI; the other three paths they
wanted are deferred. Chapter alignment is structured. Journal entries only. A revealed answer
stops counting but stays practisable, and **only an explicit button reveals**. The three
commitments this breaks are **exempted for problem sets only, and fenced**. The per-problem
concept **tags that problem's signatures**. The staff side — assignment creation and console
cleanup — **is in scope**.

## The three commitments this feature breaks

Draft 1 reversed all three and mentioned none. They are separable, and all three are exempted
**for problem-set workspaces only**.

| Commitment | Where it is stated and enforced | What this feature does |
| --- | --- | --- |
| **A7** — no "correct / incorrect / right / wrong" anywhere a student can see; colour never means correctness | `messages.py:1`, `README.md:45`; `BANNED = re.compile(r"\b(correct\|incorrect\|right\|wrong)\b")` asserted over every rendered student screen in `tests/unit/test_web.py:20` and `tests/guards/test_javascript.py:17` | Per-line ✓/✗, and "right" as a problem state |
| **T8.8** — a detected signature never reaches the student | `grading/signatures.py`; `services/diagnostics.py` | Shows the signature's sentence verbatim from attempt 2 |
| **A8** — no answer-key value reaches a student; checkpoints return a boolean only | `STATUS.md:139`, `:226`; `models/content.py` on the `answer_key` payload | Shows the expected entry on an explicit reveal |

**The fence is the deliverable, not a note.** Two guards:

1. The A7 banned-word guards gain an **explicit exemption list of problem-set routes, each with its
   reason**, in the style of `tests/guards/test_scoping.py`'s exemption sets — never a blanket skip.
2. A new guard asserts that **every problem-set route 404s for a practice-set workspace, and every
   practice-set route 404s for a problem-set workspace.** This is what keeps the exemption from
   becoming a hole: a practice-set student must remain unable to reach any of it.

`ContentPack.kind` is what the fence tests, so it has to be explicit rather than inferred.

## Goals

- An instructor writes a chapter of problems in one file and imports it with one command.
- A student works any problem, as often as they like, and is told what they misunderstood in the
  pack's own words.
- The best N of the chapter's problems count, so practising beyond the minimum can never cost a
  mark.
- An instructor can create a problem-set assignment and read a console that makes sense for one.
- Marks reach the existing CSV export and the mastery view with no new grading.
- No practice set's marks move by a single point, and no practice-set student sees any of the
  exempted behaviour.

## Non-goals

- **Only journal entries.** Adjusting entries, trial balances, statements and managerial topics are
  the PRD's phases 2 and 3.
- **One variant per problem set.** The PRD promises generated figure variants (§7.1); the owner's
  own combinatorial-variants spec concluded they *raise* authoring cost and buy uniqueness, not
  effort. That trade stays a separate decision.
- **One authoring path.** A hand-written file and a CLI. The spreadsheet import, the generator
  route and the in-app screen were all wanted and are all deferred: each would have to produce this
  format anyway, and the in-app screen is most of the PRD's shared question bank (§9).
- **No AI.** The explanations are hand-written in the signatures, which is better, and it keeps
  clear of OpenStax's no-generative-AI term.
- **No system-allocated problem pools.** Each student being given a different six needs a variant
  to *omit* a document, which `Document.variants` cannot express — it varies presentation, never
  presence. Student choice gets most of the value for almost none of the risk.
- **No per-problem mastery dimension.** See *Concepts*: Block A shows one row per chapter pack.
- **No live earned-mark count on the student's problems list.** `student/views.py` shows a student
  nothing until `Assignment.marks_released_at`; a running total here would be an exception to that
  gate, and this project is not the place to make one.

## Anti-goals

Failure even if it ships and works:

- **A practice set's marks move.** The existing rubric components divide their points across every
  document in the pack (`grading/components/documents.py:75`). Nothing here may edit them.
- **A practice-set student reaches the exempted behaviour.** The exemption is scoped to
  `kind == "problem_set"` and proved by a guard, or A7, T8.8 and A8 are simply gone.
- **A revealed answer earns marks.**
- **An attempt lost to a typo.** A submission refused for being out of balance must not consume an
  attempt, and nothing but the explicit button may reveal.
- **Per-line marks on the first attempt.** Attempt one withholds *which* line so a student has to
  think rather than walk the grid.
- **A client-side attempt counter.** A counter a student could reset by reloading turns progressive
  disclosure into "press submit twice".
- **A new route outside the scoping guarantee.** Every new route reaches `workspace_view` or
  `_assignment_or_404` and is in the guard matrix.
- **A validator that accepts a broken problem.** A problem that imports and then cannot be graded
  is worse than one that never imported.

## Constraints

- **A `Pack` requires only six fields:** `format_version`, `company`, `version`, `period`,
  `accounts`, `variants`. Journals, documents, statements, parties, checkpoints and the rubric are
  optional (`packs/schema.py`). This is what makes a problem set a viable small pack.
- **Pack sources are validated `extra="forbid"`.** Every new field goes in the Pydantic schema
  first or import rejects the whole pack.
- **`Document` has no field for a problem's prose.** Its fields are `ref`, `display_ref`, `type`,
  `kind`, `date`, `received_seq`, `guided`, `guidance`, `variants`. `guidance` is not a substitute:
  `validate._v10_guided` caps guided documents at **two** per pack. So `Document` gains
  `stem: str | None = None`.
- **`grade(work, pack, key)` is pure in the pack and the key.** No component has ever seen
  assignment state, and `tests/guards/test_import_boundaries.py` polices what `grading/` imports.
- **`import_pack_zip` refuses a repeat `source_sha256`** and any `version` ≤ the highest for that
  slug; a pack version is immutable once a workspace pins it.
- **Validators V10 and V17 require triage values in the answer key.** The importer fills them.
- **Teachers see their own sections; admins see everything.** `abort(404)`, never 403.
- **The CSP forbids inline styles**: `security.py:18`, no `unsafe-inline`. Bars are `<meter>`.
- **Tailwind v4 emits nothing for an unscanned utility**, silently.
- **One shared Neon database serves development, the tests and production.** See *The database
  problem*.
- **`ruff check originalentry tests` must stay clean** — 6 pre-existing findings as of `96753dd`.
- **Migration head is `c3e71f0a95b4`.**

## Design

### A chapter problem set is a small pack

| Pack field | What it holds |
| --- | --- |
| `company` | A stub naming the set. Slug derived from textbook and chapter, e.g. `openstax-fa-ch3`. |
| `period` | The period the problems' dates fall in. |
| `accounts` | Only the accounts the chapter's problems touch. |
| `variants` | Exactly one, code `A`. |
| `documents` | One per problem: `ref`, `date`, and the new `stem`. |
| `journals` | One general journal. |
| `rubric` | One component, `problems_best_n`. |
| `statements`, `parties`, `checkpoints` | Absent. |

The answer key carries one `expected_entries` row per problem, `triage` filled by the importer (for
a problem set every document requires an entry), and `error_signatures` as any pack has.

### Chapter metadata, and the kind

Four nullable columns on `content_pack`: `textbook`, `chapter_label`, `chapter_ordinal`, and
`kind` (`practice_set` default, or `problem_set`). Nullable and defaulted so every existing row is
untouched. `kind` decides which student screens open, which rubric applies, and what the fence
guards test.

### Marks: the best N of M

`Assignment` gains `problems_required: int | None`, null for every practice set.

A new rubric component, **`problems_best_n`**, added to `KNOWN_COMPONENTS`:

- Scores each problem independently from the answer key, as `entry_accuracy` does for one document.
- Takes the highest `problems_required` scores and divides the component's points among those.
- **Excludes any problem whose answer has been revealed**, whatever it scored.
- The denominator is always `problems_required`, never the number attempted — otherwise one perfect
  problem would be full marks.
- `problems_required` null, zero, or greater than the problem count is a **validation error at
  assignment creation**, not a runtime fallback: a silent default would rescale a whole section.

**A new component, never an edit to an existing one.**

### How the engine learns the count and the reveals

`problems_required` lives on `Assignment` and the reveals live in `problem_attempt`, neither of
which `grade()` can see. **`StudentWork` and `grading/workspace.load_work` carry both in**, so
`grade()`'s signature is unchanged, every existing component and the golden tests are untouched,
and `grading/` imports nothing new. This is the contained option of the three; moving the count
into the pack rubric would keep grading pack-pure but put a per-section number in immutable
content, and changing `grade()`'s signature ripples through every component test.

### Attempts and progressive feedback

Unlimited attempts. The escalation is **server-side state**, and **only the explicit button
reveals**:

| State | What the student sees |
| --- | --- |
| Attempt 1 | The entry judged as a whole and which *kind* of thing is wrong — an account, an amount, a direction — with a hint at the reasoning. No per-line marks. |
| Attempt 2+ | Per-line ✓/✗ and the matching signature's sentence verbatim. The fullest feedback short of the entry, for as many attempts as they want. |
| Reveal (button) | The expected entry. The problem stops counting from this point and is labelled as revealed. |
| After reveal | The answer stays visible; further submissions are practice and change no mark. |

**A submission refused for being out of balance does not consume an attempt.** The balance check
already runs before the write (`messages.out_of_balance`); a typo must not advance the disclosure.

A new table, `problem_attempt`, keyed `(workspace_id, document_ref)`: `attempts: int`,
`answer_shown_at: datetime | None`, `last_submitted_at`.

### The submitted entry, and the closed routes

Each submission **replaces** that problem's previous entry — the existing void-and-record path, not
a second live entry. Otherwise `work.entries_for_document(ref)` returns more than one and
`documents.py:88-90` sets `needs_review` on every problem of every workspace, which would fill the
grading queue with flags that mean nothing.

**The practice-set student routes 404 in a problem-set workspace** — journals, ledgers, statements,
trial balance, the print record, submit-readiness. They are built for a cycle this content has no
part of, and leaving them open lets a student record entries outside the attempt machinery
entirely. The reverse holds too, and both directions are the fence guard above.

### The student screens

Under the existing workspace prefix, so they inherit `workspace_view` and therefore the scoping and
the read-only-after-submission behaviour:

- `GET  /w/<workspace>/<company_slug>/problems` — the chapter's problems with their state: not
  started, attempted *n* times, matched, or revealed. How many count. **No running mark**, per the
  marks-release gate.
- `GET  /w/<workspace>/<company_slug>/problems/<ref>` — one problem: stem, a small journal grid,
  and whatever feedback its state has earned.
- `POST /w/<workspace>/<company_slug>/problems/<ref>` — submit an attempt.
- `POST /w/<workspace>/<company_slug>/problems/<ref>/answer` — reveal, explicitly.

### Concepts

Draft 1 claimed a per-problem concept "feeds the mastery view from the day it is imported". That
was false: `ConceptTag` is keyed by component or signature key, and `services/mastery.py` pools
process concepts by *component* key — so one chapter pack with one component can carry exactly one
concept for all ten problems.

What happens instead: **the importer writes a `ConceptTag` for every signature a problem declares**,
defaulting to the problem's own `concept`. So the mistakes block names concepts per misconception,
which is already how topic concepts work and needs no new machinery. Block A shows one row for the
whole chapter.

This also closes a loop: `tests/guards/test_concept_tags.py::test_every_signature_any_pack_declares_is_tagged`
scans `packs/*/source.json`, so once chapter files live there every hand-written signature key
*must* be tagged — and the importer writing those tags is what satisfies it.

### The staff side

**Assignment creation.** The new-assignment screen learns to pick a chapter problem set and set
`problems_required`, validated against the pack's problem count.

**Console cleanup**, keyed on `kind == "problem_set"`:

- Diagnostics hides the triage tallies, which would report every problem "not handled" for every
  student, since the key must still carry triage values to satisfy V10.
- Progress's stage ladder (Documents → Journalising → Posted → Statements → Closed) ends at
  Journalising.
- The mastery blocks and the marks CSV need no change.

Without both halves the feature is unusable by the instructors the PRD aims at. This is scope draft
1 did not budget for and it is the largest staff-side piece.

### Authoring: one file, one command, one validator

A hand-written YAML file per chapter, **committed under `packs/`** so the concept-tag guard and the
pack-source tests see it, translated to a pack source on import and put through the existing
`import_pack_zip` path — one importer, not two.

```yaml
textbook: OpenStax Principles of Financial Accounting
chapter: 3
chapter_label: "Analyzing and Recording Transactions"
accounts: [...]            # only what the problems touch
problems:
  - ref: P3-02
    date: 2026-10-05
    concept: debit_credit  # required; must name a live Concept; defaults its signatures' tags
    stem: >
      On 5 October the business bought equipment for $4,800, paying $1,800 cash and
      agreeing to pay the rest later. Record the entry.
    entry:
      - { account: "150", debit: 480000 }   # cents
      - { account: "101", credit: 180000 }
      - { account: "201", credit: 300000 }
    signatures:
      - key: supplies_not_equipment
        label: >
          Something bought to use for years recorded as supplies, which are used up
        detect: { type: entry_line, document: P3-02, account: "140", side: debit }
```

`flask problems import <file>` builds the source, validates, imports, and writes the signature
concept tags.

**The validator rejects, loudly:** debits ≠ credits; an account the file does not declare; a
`concept` naming no live `Concept`; a duplicate `ref`; a `detect` naming a document not in the file;
an empty `stem`. Amounts are cents, which is a real trap for a YAML author, so errors report both
forms.

**Identity and re-import.** The slug comes from textbook and chapter; the version auto-increments,
since `import_pack_zip` refuses a repeat sha or a version that does not advance. Fixing a typo
mid-term therefore creates a **new pack version**, and an assignment already pinned to the old one
keeps it — pack immutability holds, which means a mid-term correction reaches only sections
assigned after it. That is a real limitation, stated below.

## The database problem

One shared Neon database serves development, the test suite and production. `flask problems import`
and the migration both write to it, `test_schema_drift.py` compares the models against it, and
nothing `db`-marked passes until the migration is applied. That forces migration-first sequencing
and means almost nothing can be verified before it has touched production.

**This is not a design decision and the spec cannot settle it.** It has cost real time on every
project so far and it is worth the owner's attention before a project that adds four columns, a
table, a backfill and a content-import path.

## Known limitations

- **Student choice is weak against copying.** Two students may do the same six and share answers.
- **A problem set's "company" is a stub.** It appears nowhere a student sees, but anybody reading
  `content_pack` will meet rows that are not companies.
- **A mid-term correction only reaches later sections.** Pack versions are immutable once pinned.
- **A problem that suits two chapters is written twice**, until a shared bank exists.
- **Changing `problems_required` after students have worked changes every mark in the section**, as
  any rubric change would.
- **No partial credit across attempts.** The mark is the final state of each counted problem.
  Deliberate: the alternative penalises using the feedback the design exists to give.
- **Block A shows one row per chapter**, not per problem. The mistakes block carries the detail.
- **A7, T8.8 and A8 now have an exemption.** It is scoped and guarded, and it is still an exemption
  — the first in this product. If the guard is ever weakened the commitments are gone with it.

## Left to the builder

- Whether `problem_attempt` is its own table or a JSONB column on `workspace`; the requirement is
  that the count is server-side and survives a reload.
- How attempt 1's "which kind of thing is wrong" is computed — comparing the submitted lines'
  accounts, amounts and sides against the key gives it; the wording is the builder's so long as it
  never names the line.
- Whether the problems list is its own template or a block on an existing one.
- The YAML-to-pack-source translator's internal shape, so long as there is one importer.
- Whether `flask problems import` takes one file or a directory.
- Synthesising the pack fields a problem set does not author: `display_ref`, `received_seq`,
  `accent_hex`, the monogram, the period bounds.
