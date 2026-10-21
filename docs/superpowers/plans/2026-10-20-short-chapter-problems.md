# Short chapter-aligned problems — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An instructor writes a chapter of short journal-entry problems in one file, imports it with one command, and assigns it; students work any problem as often as they like and are told what they misunderstood, with the best N counting.

**Architecture:** A chapter problem set is a small `PackVersion` — a company stub, a period, the accounts those problems touch, one variant, one document per problem — so the ledger engine, partial credit, the error signatures, marks export and section scoping work unchanged. What is new: one rubric component that scores the best N, a server-side attempt counter that drives three levels of feedback, four student routes, and the fence that keeps all of it away from practice sets.

**Tech Stack:** Flask 3.1, SQLAlchemy 2.0, Flask-Migrate/Alembic, Pydantic (pack schema), Jinja2, Tailwind v4 (prebuilt), PyYAML, pytest against Postgres.

**Spec:** `docs/superpowers/specs/2026-10-20-short-chapter-problems-design.md`

## Global Constraints

Copied from the spec. Every task's requirements implicitly include these.

- **A7, T8.8 and A8 are exempted for problem-set workspaces only.** A7: no "correct / incorrect / right / wrong" where a student can see it, asserted by `BANNED` in `tests/unit/test_web.py:20` and `tests/guards/test_javascript.py:17`. T8.8: a signature never reaches the student. A8: no answer-key value reaches a student. **The fence is a deliverable, not a note** — an explicit exemption list with reasons, plus a guard that every problem-set route 404s for a practice-set workspace and the reverse.
- **No existing rubric component may be edited.** They divide points across every document in the pack (`grading/components/documents.py:75`). A practice set's marks must not move by one point.
- **An attempt lost to a typo is a defect.** A submission refused for being out of balance must not consume an attempt, and only the explicit reveal endpoint may reveal.
- **Attempt state is server-side.** A counter a student could reset by reloading turns progressive disclosure into "press submit twice".
- **`abort(404)`, never 403.** Teachers see their own sections; admins see everything.
- **Pack sources are validated `extra="forbid"`** (`packs/schema.py:25-27`): a new field goes in the Pydantic schema first or import rejects the whole pack.
- **The CSP forbids inline styles** (`security.py:18`, no `unsafe-inline`). Bars are `<meter>`.
- **Tailwind v4 emits nothing for an unscanned utility**, silently. Verify each class against `static/dist/app.css`; note that CSS escapes `.` and `/` in class names, so check for the escaped form.
- **Amounts are cents** throughout.
- **`ruff check originalentry tests` must stay clean** — 6 pre-existing findings in untouched files as of `e2805b9`.
- **Migration head is `c3e71f0a95b4`.** New revisions chain from it.
- **The test suite runs against the Neon development branch** when `TEST_DATABASE_URL` is set, and prints a banner when it is not (`tests/database_target.py`). Apply migrations there first; production is a separate, consented step. The full suite is ~56 minutes and two concurrent runs deadlock.

## Review Focus

Input classes the spec implies that no happy path exercises. Each has a test in the task that owns it.

1. **An out-of-balance submission.** Refused, and it must not consume an attempt or advance the disclosure — otherwise a typo costs a problem. (Task 4)
2. **`problems_required` null, zero, or larger than the problem count.** A validation error at assignment creation, never a runtime default, because a silent fallback rescales a whole section. (Task 6)
3. **A practice-set student reaching a problem-set route, and the reverse.** 404 both ways; this is the fence that keeps the A7/T8.8/A8 exemption from being a hole. (Task 5)
4. **A problem revealed and then answered perfectly.** Scores nothing toward the best N, whatever the final entry says. (Task 2)
5. **Re-importing a corrected chapter.** A new pack version; an assignment already pinned to the old one keeps it, so a mid-term fix reaches only later sections. (Task 3)

---

## File Structure

| File | Responsibility |
| --- | --- |
| `originalentry/models/content.py` (modify) | `ContentPack.kind`, `.textbook`, `.chapter_label`, `.chapter_ordinal` |
| `originalentry/models/work.py` (modify) | `Assignment.problems_required`; `ProblemAttempt` |
| `originalentry/packs/schema.py` (modify) | `Document.stem`; chapter fields on `Company` |
| `migrations/versions/<rev>_problem_sets.py` (create) | Four `content_pack` columns, `assignment.problems_required`, `problem_attempt`, `kind` backfill |
| `originalentry/grading/components/problems.py` (create) | `problems_best_n` — the only new scoring rule |
| `originalentry/grading/models.py` (modify) | `StudentWork.problems_required`, `.revealed` |
| `originalentry/grading/workspace.py` (modify) | `load_work` fills both |
| `migrations/versions/<rev>_tag_problems_best_n.py` (create) | The `ConceptTag` that `KNOWN_COMPONENTS` obliges |
| `originalentry/packs/validate.py` (modify) | `problems_best_n` into `KNOWN_COMPONENTS` |
| `originalentry/problems/chapter.py` (create) | The YAML format: parse, validate, translate to a pack source |
| `originalentry/problems/importing.py` (create) | Next version, the zip, the import, and the signature concept tags |
| `tests/guards/test_concept_tags.py` (modify) | Walk `packs/chapters/*.yaml` too, so a chapter's signatures are guarded |
| `originalentry/cli.py` (modify) | `flask problems import` |
| `originalentry/services/problems.py` (create) | Attempts, submit-and-replace, reveal, feedback level |
| `originalentry/student/views.py` (modify) | The four problem routes |
| `originalentry/templates/student/problems.html` (create) | The chapter's problem list |
| `originalentry/templates/student/problem.html` (create) | One problem and its feedback |
| `originalentry/staff/views.py` (modify) | Chapter picker and `problems_required` on assignment creation |
| `originalentry/templates/staff/diagnostics.html`, `progress.html` (modify) | Hide blocks meaningless for a problem set |
| `tests/guards/test_problem_set_fence.py` (create) | Both directions of the fence; the A7 exemption list |

---

### Task 1: The schema, the models and the migration

**Files:**
- Modify: `originalentry/models/content.py`, `originalentry/models/work.py`, `originalentry/packs/schema.py`
- Create: `migrations/versions/<rev>_problem_sets.py`
- Test: `tests/integration/test_problem_set_schema.py`

**Interfaces:**
- Produces: `ContentPack.kind: str` (default `"practice_set"`), `.textbook: str | None`, `.chapter_label: str | None`, `.chapter_ordinal: int | None`; `Assignment.problems_required: int | None`; `models.ProblemAttempt` with `id`, `workspace_id` FK, `document_ref: str(40)`, `attempts: int` default 0, `answer_shown_at: datetime | None`, `last_submitted_at: datetime | None`, `UniqueConstraint("workspace_id", "document_ref")`; `schema.Document.stem: str | None = None`; `schema.Company.textbook`, `.chapter_label`, `.chapter_ordinal`, all optional. Constants `KIND_PRACTICE_SET = "practice_set"` and `KIND_PROBLEM_SET = "problem_set"` in `models/content.py`.

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_problem_set_schema.py`, `pytestmark = pytest.mark.db`.

```python
def test_every_existing_pack_is_a_practice_set(session):
    """The backfill, and the default: nothing that exists becomes a problem set by accident."""
    kinds = set(session.scalars(db.select(ContentPack.kind)).all())
    assert kinds <= {KIND_PRACTICE_SET, KIND_PROBLEM_SET}
    assert session.scalars(db.select(ContentPack).filter_by(kind=None)).first() is None


def test_an_attempt_row_is_unique_per_workspace_and_problem(session):
    """Two rows for one problem would make the attempt count depend on which was read first."""
    # add two ProblemAttempt rows with the same (workspace_id, document_ref)
    with pytest.raises(IntegrityError):
        session.flush()


def test_a_document_can_carry_a_problem_stem():
    """schema.Document had nowhere for prose: guidance is capped at two documents per pack by
    validate._v10_guided, so it cannot hold ten stems."""
    document = schema.Document(ref="P3-02", display_ref="P3-02", type="problem",
                               date=date(2026, 10, 5), received_seq=1, stem="On 5 October...")
    assert document.stem.startswith("On 5 October")


def test_the_pack_schema_still_forbids_an_unknown_field():
    """extra="forbid" is what makes a typo in a chapter file an import failure rather than a
    silently ignored line."""
    with pytest.raises(ValidationError):
        schema.Document(ref="x", display_ref="x", type="problem", date=date(2026, 1, 1),
                        received_seq=1, stemm="typo")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/integration/test_problem_set_schema.py -v`
Expected: FAIL — `ImportError` for `KIND_PRACTICE_SET` / `ProblemAttempt`.

- [ ] **Step 3: Add the model and schema fields**

The columns and constants from the Interfaces block. `ProblemAttempt` goes in `models/work.py` beside the other workspace-scoped tables; export it and the two constants from `models/__init__.py`. Index `problem_attempt.workspace_id` — every problem page reads the workspace's rows together.

- [ ] **Step 4: Write the migration**

`down_revision = 'c3e71f0a95b4'`. Four nullable `content_pack` columns, `kind` with a server default of `'practice_set'` and `NOT NULL` after a backfill of existing rows; `assignment.problems_required` nullable; `problem_attempt` with its unique constraint and index. Follow `migrations/versions/c3e71f0a95b4_concepts.py` for layout. `downgrade()` drops all of it.

- [ ] **Step 5: Apply it to the development branch and run the tests**

Run the upgrade against `TEST_DATABASE_URL_DIRECT`, not production. Production is a separate step at the end of the plan, with the owner's consent.

Run: `.venv/bin/python -m pytest tests/integration/test_problem_set_schema.py tests/guards -q`
Expected: PASS, including `test_schema_drift.py` — which is the proof the models and the migration agree.

- [ ] **Step 6: Commit**

```bash
git add originalentry/models/ originalentry/packs/schema.py migrations/versions/*_problem_sets.py \
        tests/integration/test_problem_set_schema.py
git commit -m "feat: the shape of a problem set"
```

---

### Task 2: `problems_best_n`, and the engine learning the count

**Files:**
- Create: `originalentry/grading/components/problems.py`
- Modify: `originalentry/grading/components/__init__.py`, `originalentry/grading/models.py`, `originalentry/grading/workspace.py`, `originalentry/packs/validate.py`
- Create: `migrations/versions/<rev>_tag_problems_best_n.py`
- Test: `tests/unit/test_problems_best_n.py`, `tests/integration/test_problem_marks.py`

**Interfaces:**
- Consumes: `models.ProblemAttempt` (Task 1); `grading.components.documents`'s `_key_amounts`, `_student_amounts`, `_compare` — the per-document comparison this mirrors; `ComponentResult(key, label, points, max_points, evidence, needs_review, review_reasons)`; `EvidenceRow(item, detail, credit, max_credit)`.
- Produces: `problems_best_n(work, pack, key, points) -> ComponentResult`, registered in `COMPONENTS` and `KNOWN_COMPONENTS`, with the `ConceptTag` that `KNOWN_COMPONENTS` obliges (see Step 4); `StudentWork.problems_required: int | None = None` and `StudentWork.revealed: frozenset[str] = frozenset()`, both filled by `load_work`.

- [ ] **Step 1: Write the failing unit tests**

Create `tests/unit/test_problems_best_n.py`. No database: build `StudentWork` and a key directly.

```python
def test_only_the_best_n_count():
    """Twenty problems, six required: the six highest scores, and the rest are ignored
    entirely -- not averaged in, not subtracted."""

def test_the_denominator_is_n_not_the_number_attempted():
    """One problem answered perfectly out of six required is one sixth, not full marks."""

def test_a_revealed_problem_scores_nothing_however_good_the_entry():
    """Review Focus 4. The entry may be perfect; the answer was shown."""

def test_a_revealed_problem_does_not_take_one_of_the_n_slots():
    """Six required, one revealed, seven attempted: the best six of the six unrevealed count, so
    revealing one of many costs nothing -- which is what makes the reveal humane."""

def test_more_than_one_live_entry_for_a_problem_asks_for_review():
    """Mirrors entry_accuracy: it should not happen, because submitting replaces, and if it does
    the mark is not to be trusted."""
```

And in `tests/integration/test_problem_marks.py`, `pytestmark = pytest.mark.db`:

```python
def test_the_new_component_carries_a_concept(session):
    """tests/guards/test_concept_tags.py::test_every_component_key_is_tagged asserts
    KNOWN_COMPONENTS <= tagged, so adding a component key without its tag fails that guard
    immediately. Assert the tag exists and names a live Concept."""
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_problems_best_n.py -v`
Expected: FAIL — `ImportError: cannot import name 'problems_best_n'`.

- [ ] **Step 3: Implement the component**

`problems_best_n(work, pack, key, points) -> ComponentResult` in the new file. Score each `key.expected_entries` row exactly as `entry_accuracy` does — reuse its helpers rather than reimplementing the comparison — then drop every problem in `work.revealed`, take the `work.problems_required` highest shares, and divide `points` among that many slots. One `EvidenceRow` per problem, including the excluded ones, so the evidence says why a problem earned nothing.

Add to `COMPONENTS` and to `validate.KNOWN_COMPONENTS`.

- [ ] **Step 4: Tag the new component**

`KNOWN_COMPONENTS` is not a private list: `test_every_component_key_is_tagged` requires a
`ConceptTag` for every key in it, so Step 3 on its own turns that guard red. Write a migration
chaining from Task 1's that inserts one `artifact_kind="component"` tag for `problems_best_n`
against the existing process concept for recording a journal entry — the same concept
`entry_accuracy` carries, since both measure whether an entry was recorded correctly. Look the
concept up by its `key` in the migration rather than hardcoding an id; `downgrade()` deletes the
tag. Apply it to the development branch.

- [ ] **Step 5: Carry the count and the reveals into the engine**

Add the two fields to `StudentWork` **with defaults**, so every existing construction and every golden test is untouched, and fill them in `load_work` from `Assignment.problems_required` and the workspace's `ProblemAttempt` rows where `answer_shown_at is not None`. `grade()`'s signature does not change and `grading/` imports nothing new — `tests/guards/test_import_boundaries.py` polices that.

- [ ] **Step 6: Write the remaining integration tests**

In `tests/integration/test_problem_marks.py`:

```python
def test_marks_follow_the_reveal(session):
    """Grade, reveal one problem, grade again: the mark falls and the evidence says why."""

def test_a_practice_set_pack_grades_exactly_as_before(session):
    """The anti-goal, executable. Grade a testco_alpha workspace, record every component's
    points, then assert the same values after this task's changes are in place."""
```

- [ ] **Step 7: Run all three suites**

Run: `.venv/bin/python -m pytest tests/unit/test_problems_best_n.py tests/integration/test_problem_marks.py tests/golden tests/guards/test_concept_tags.py -q`
Expected: PASS. The golden tests are the second proof that no practice set's marks moved; the
concept-tag guard is the proof Step 4 landed.

- [ ] **Step 8: Commit**

```bash
git add originalentry/grading/ originalentry/packs/validate.py migrations/versions/*_tag_problems_best_n.py \
        tests/unit/test_problems_best_n.py tests/integration/test_problem_marks.py
git commit -m "feat: problems_best_n, and the engine learning what counts"
```

---

### Task 3: The chapter file, its validator, and the import

**Files:**
- Create: `originalentry/problems/__init__.py`, `originalentry/problems/chapter.py`, `originalentry/problems/importing.py`
- Modify: `originalentry/cli.py`
- Test: `tests/unit/test_chapter_file.py`, `tests/integration/test_chapter_import.py`
- Create: `packs/chapters/openstax-fa-ch3.yaml` — one real chapter, three problems, as the fixture and the first content

**Interfaces:**
- Consumes: Task 1's schema fields; Task 2's `problems_best_n` in `KNOWN_COMPONENTS` (without it `validate._v15_rubric` rejects the pack); `models.Concept`, `models.ConceptTag`, `KIND_SIGNATURE`; `packs.importing.import_pack_zip`.
- Produces: `chapter.parse(text: str) -> Chapter` raising `ChapterRefused` with every problem found, not just the first; `chapter.to_pack_source(ch: Chapter, *, version: int) -> tuple[dict, dict]` returning `(pack, answer_key)`; `chapter.to_zip(pack: dict, keys: dict[str, dict]) -> io.BytesIO` laying out `pack.json` and `answer_keys/<code>.json`, which is what `import_pack_zip` reads (`packs/zip_reader.py:24`) — the caller wraps `to_pack_source`'s single key as `{"A": answer_key}`, since a problem set has one variant; `importing.next_version(session, slug) -> int`; `importing.import_chapter(session, text) -> PackVersion`, which also writes one `ConceptTag` per declared signature; `flask problems import <path>`.

**Why `version` is a parameter.** The spec has the version auto-increment, and `_v14_catalogue`
refuses a version that does not advance — but the highest existing version is a database fact.
Keeping it out of `to_pack_source` is what lets every test in Step 1 run with no session.

- [ ] **Step 1: Write the failing validator tests**

Create `tests/unit/test_chapter_file.py`. No database — the parse and the translation are pure.

```python
def test_an_unbalanced_entry_is_refused():
    """Debits must equal credits. In cents, so the error reports both forms -- 480000 and
    $4,800.00 -- because a YAML author writing dollars is the likeliest mistake in this format."""

def test_an_account_the_file_does_not_declare_is_refused():

def test_a_duplicate_ref_is_refused():

def test_an_empty_stem_is_refused():

def test_a_signature_naming_another_document_is_refused():

def test_every_problem_is_reported_not_just_the_first():
    """A chapter with three bad problems reports three. Fixing them one import at a time is the
    difference between a usable format and an unusable one."""

def test_the_translation_produces_a_pack_the_schema_accepts():
    """schema.load_pack and schema.load_answer_key on the output, then validate.warn_pack with no
    errors -- the real gate, since extra="forbid" and V15 both bite at import."""

def test_the_translation_fills_triage_for_every_problem():
    """V10 and V17 want triage values; for a problem set every document requires an entry."""
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_chapter_file.py -v`
Expected: FAIL — `ModuleNotFoundError: originalentry.problems.chapter`.

- [ ] **Step 3: Write the parser, the validator and the translator**

`chapter.py`: a `Chapter` dataclass, `parse` (PyYAML `safe_load`, then the checks above, collecting every problem into one `ChapterRefused`), `to_pack_source`, and `to_zip`. The translator synthesises what a chapter does not author — `display_ref` from `ref`, `received_seq` from position, the company stub's slug from textbook and chapter, `accent_hex` and monogram, the period bounds from the problems' dates — and sets the rubric to one `problems_best_n` component.

A concept that names no live `Concept` row is a **database** check and belongs in `importing.py`, not here: `chapter.py` stays pure so these tests need no session.

- [ ] **Step 4: Write the failing import tests**

In `tests/integration/test_chapter_import.py`:

```python
def test_importing_a_chapter_creates_a_problem_set_pack(session):
    """kind == problem_set, the chapter metadata on content_pack, one document per problem."""

def test_a_concept_that_names_no_live_concept_is_refused(session):

def test_each_declared_signature_gets_a_concept_tag(session):
    """What makes the mistakes block name a concept for a chapter problem, and what satisfies
    test_every_signature_any_pack_declares_is_tagged once Step 6 extends its walk."""

def test_reimporting_a_corrected_chapter_makes_a_new_version(session):
    """Review Focus 5. import_pack_zip refuses a repeat sha and a version that does not advance,
    so a fix is a new version -- and an assignment pinned to the old one keeps it."""
```

- [ ] **Step 5: Implement the import and the CLI**

`import_chapter` computes the next version with `next_version`, translates, checks every `concept` against a live `Concept`, builds the zip, imports it through `import_pack_zip`, then writes the signature tags. Nothing is written to `packs/<slug>/source.json`: the chapter file is the committed source of truth and a generated copy beside it would be a second one that could disagree. `flask problems import <path>` wraps it and prints what it created. Register it beside the existing `packs` commands in `cli.py`.

- [ ] **Step 6: Write the chapter file, extend the signature guard, and import**

`packs/chapters/openstax-fa-ch3.yaml`, three problems, the spec's example as the first.

Then extend `_signature_keys_on_disk()` in `tests/guards/test_concept_tags.py` to walk
`packs/chapters/*.yaml` as well as `packs/*/source.json`, and raise the floor in
`test_the_pack_sources_declare_signatures_at_all` to include the chapter's. The spec wants every
hand-written signature key tagged; that guard's glob is `packs/*/source.json`, so without this a
chapter's signatures are never checked and the loop the spec describes silently does not close.
Extending the walk, rather than committing a generated `source.json`, keeps one source of truth.

Import the chapter against `TEST_DATABASE_URL_DIRECT`.

Run: `.venv/bin/python -m pytest tests/unit/test_chapter_file.py tests/integration/test_chapter_import.py tests/guards/test_concept_tags.py -q`
Expected: PASS. The concept-tag guard is the one that proves the signature tags landed — and it now
fails if a later chapter declares a signature nobody tagged.

- [ ] **Step 7: Commit**

```bash
git add originalentry/problems/ originalentry/cli.py packs/chapters/ \
        tests/guards/test_concept_tags.py tests/unit/test_chapter_file.py \
        tests/integration/test_chapter_import.py
git commit -m "feat: a chapter of problems in one file, imported by one command"
```

---

### Task 4: Attempts, replacement, reveal, and the three feedback levels

**Files:**
- Create: `originalentry/services/problems.py`
- Test: `tests/unit/test_problem_feedback.py`, `tests/integration/test_problem_attempts.py`

**Interfaces:**
- Consumes: `models.ProblemAttempt` (Task 1); `services.entries.void_entry`; the existing record-an-entry form and its balance check — `originalentry/forms/entries.py:109`, which reports through `messages.out_of_balance`. Reuse the form; a second balance check would be a second answer to the same question.
- Produces:
  ```python
  LEVEL_SHAPE = 1      # which kind of thing is wrong; never which line
  LEVEL_LINES = 2      # per-line marks and the signature's sentence
  LEVEL_ANSWER = 3     # the expected entry; only after an explicit reveal

  def feedback_level(attempt: ProblemAttempt | None) -> int
  def submit(session, workspace, document_ref, lines, *, actor) -> ProblemAttempt
  def reveal(session, workspace, document_ref, *, actor) -> ProblemAttempt
  def shape_of_error(expected, submitted) -> str   # "account" | "amount" | "direction" | "balance"
  ```

- [ ] **Step 1: Write the failing unit tests**

`tests/unit/test_problem_feedback.py` — no database; `feedback_level` and `shape_of_error` are pure.

```python
def test_the_first_attempt_gets_shape_only():
def test_the_second_attempt_and_every_later_one_gets_the_lines():
    """Level 2 for attempt 2, 3, 9 -- unlimited attempts, and only the button goes further."""
def test_only_a_reveal_reaches_the_answer():
    """answer_shown_at set -> LEVEL_ANSWER. Attempt count never reaches it on its own."""
def test_shape_names_the_kind_of_error_without_naming_the_line():
    """A wrong account reads "account", a wrong figure "amount", a reversed entry "direction" --
    and none of the returned strings contains a line number or an account code."""
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_problem_feedback.py -v`
Expected: FAIL — `ModuleNotFoundError: originalentry.services.problems`.

- [ ] **Step 3: Write the failing integration tests**

`tests/integration/test_problem_attempts.py`:

```python
def test_an_out_of_balance_submission_does_not_consume_an_attempt(session):
    """Review Focus 1, and the anti-goal: a typo must not advance the disclosure. Submit
    unbalanced twice, then assert attempts is still 0 and the level is still LEVEL_SHAPE."""

def test_submitting_replaces_the_previous_entry(session):
    """Otherwise entries_for_document returns two, and every problem of every workspace asks for
    review. Assert exactly one live entry after three submissions, and that the voided ones are
    kept."""

def test_the_attempt_count_survives_a_reload(session):
    """Server-side state: read it back from a fresh session, not from anything the page carried."""

def test_reveal_is_recorded_once_and_is_not_undone_by_a_later_submission(session):
```

- [ ] **Step 4: Implement the service**

`submit` runs the balance check first and returns without touching `ProblemAttempt` when it fails; otherwise voids the problem's live entry, records the new one, and increments. `reveal` stamps `answer_shown_at` and is idempotent. `feedback_level` reads the row.

- [ ] **Step 5: Run both suites**

Run: `.venv/bin/python -m pytest tests/unit/test_problem_feedback.py tests/integration/test_problem_attempts.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add originalentry/services/problems.py tests/unit/test_problem_feedback.py \
        tests/integration/test_problem_attempts.py
git commit -m "feat: attempts that escalate, and a typo that costs nothing"
```

---

### Task 5: The student screens, and the fence

**Files:**
- Modify: `originalentry/student/views.py`
- Create: `originalentry/templates/student/problems.html`, `originalentry/templates/student/problem.html`
- Modify: `tests/unit/test_web.py`, `tests/guards/test_javascript.py` (the A7 exemption list), `tests/guards/test_scoping.py`
- Create: `tests/guards/test_problem_set_fence.py`
- Test: `tests/integration/test_problem_screens.py`

**Interfaces:**
- Consumes: Task 4's `feedback_level`, `submit`, `reveal`, `shape_of_error`; `KIND_PROBLEM_SET`.
- Produces: endpoints `student.problems`, `student.problem`, `student.problem_submit`, `student.problem_reveal`, all under `/w/<workspace>/<company_slug>/problems…` and therefore all through `@workspace_view`.

- [ ] **Step 1: Write the failing fence guard**

Create `tests/guards/test_problem_set_fence.py`, `pytestmark = pytest.mark.db`. This is the spec's named deliverable: without it the A7/T8.8/A8 exemption is a hole.

```python
PROBLEM_SET_ROUTES = {
    "student.problems": "the chapter's problem list",
    "student.problem": "one problem, its grid and its feedback",
    "student.problem_submit": "an attempt",
    "student.problem_reveal": "the expected entry, which A8 otherwise forbids",
}


def test_every_problem_set_route_404s_in_a_practice_set_workspace(client, session):
    """Review Focus 3. The exemption is scoped to kind == problem_set; a practice-set student
    must be unable to reach any of it, or A7, T8.8 and A8 are simply gone."""


def test_the_practice_set_routes_404_in_a_problem_set_workspace(client, session):
    """The other direction: journals, ledgers, statements, the trial balance and the print record
    are built for a cycle this content has no part of, and leaving them open would let a student
    record entries outside the attempt machinery."""


def test_the_a7_exemption_list_names_only_real_routes(app):
    """An exempt name matching no endpoint stops excluding anything, silently."""
```

- [ ] **Step 2: Scope the A7 guards**

`tests/unit/test_web.py` and `tests/guards/test_javascript.py` render every student route and fail on `BANNED`. Add an explicit exemption keyed by endpoint, each entry carrying its reason, in the style of `tests/guards/test_scoping.py`'s exemption sets — **never a blanket skip**. The exemption list is the one in Step 1, imported, so there is one list and not two.

- [ ] **Step 3: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/guards/test_problem_set_fence.py -v`
Expected: FAIL — `BuildError` for `student.problems`.

- [ ] **Step 4: Write the failing screen tests**

`tests/integration/test_problem_screens.py`:

```python
def test_the_list_shows_each_problem_s_state_and_how_many_count(client, session):
    """Not started, attempted n times, matched, revealed -- and NO running mark, because
    student/views.py shows a student nothing until Assignment.marks_released_at."""

def test_the_first_attempt_does_not_say_which_line_is_wrong(client, session):
    """The whole of the progressive design. Assert the page names no account code and no line
    number after one attempt."""

def test_the_second_attempt_shows_the_lines_and_the_signature(client, session):

def test_the_answer_appears_only_after_the_reveal_button(client, session):

def test_a_submitted_workspace_is_read_only(client, session):
    """workspace_view already enforces it; this proves the new routes inherit it rather than
    writing their own path around it."""
```

- [ ] **Step 5: Add the routes and the templates**

Four routes as named. Each resolves its problem from the pack's documents and 404s on an unknown ref. The templates show the stem, a journal grid, and whatever the level has earned.

Verify every utility class against the built stylesheet before using it — and check for the CSS-escaped form of any class containing `.` or `/`.

- [ ] **Step 6: Add the routes to the scoping matrix**

They take `<workspace>` and go through `@workspace_view`, so `tests/guards/test_structure.py` and the `/w/` half of the scoping matrix cover them. Add `document_ref` to `PLACEHOLDERS` with a real problem ref, and note why in the comment: the admission walks enter the route and a bogus ref would 404 there, which those walks report as a scoping refusal.

- [ ] **Step 7: Run the guards and the screens**

Run: `.venv/bin/python -m pytest tests/guards tests/integration/test_problem_screens.py -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add originalentry/student/views.py originalentry/templates/student/problem*.html \
        tests/guards/ tests/unit/test_web.py tests/integration/test_problem_screens.py
git commit -m "feat: the problem screen, and the fence around its exemption"
```

---

### Task 6: The staff side

**Files:**
- Modify: `originalentry/staff/views.py`, `originalentry/services/assignments.py`
- Modify: `originalentry/templates/staff/assignment_new.html`, `diagnostics.html`, `progress.html`
- Test: `tests/integration/test_problem_set_assignment.py`

**Interfaces:**
- Consumes: `KIND_PROBLEM_SET`; `Assignment.problems_required` (Task 1).
- Produces: `create_assignment` accepting `problems_required`, and refusing it when invalid.

- [ ] **Step 1: Write the failing tests**

`tests/integration/test_problem_set_assignment.py`:

```python
def test_a_problem_set_assignment_records_how_many_count(client, session):

def test_problems_required_larger_than_the_chapter_is_refused(client, session):
    """Review Focus 2. A 422 form error naming the problem count, not a runtime fallback: a
    silent default rescales every mark in the section."""

def test_problems_required_of_zero_or_absent_is_refused_for_a_problem_set(client, session):

def test_a_practice_set_assignment_still_needs_no_problems_required(client, session):
    """The field is null for every practice set and nothing about them changes."""

def test_diagnostics_hides_the_triage_block_for_a_problem_set(client, session):
    """It would report every problem "not handled" for every student, because the key carries
    triage values to satisfy V10."""

def test_progress_stops_at_journalising_for_a_problem_set(client, session):
    """The ladder's later stages -- Posted, Statements, Closed -- have no meaning here."""


def test_a_problem_set_s_marks_reach_the_csv_and_the_mastery_view(client, session):
    """The spec's fifth goal, and the whole reason a problem set is a pack: it says these "need no
    change", which is a claim and not a fact until something asserts it. Grade a problem-set
    workspace, then assert its mark appears in the marks CSV and the chapter appears as a row in
    Diagnostics' Block A."""
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/integration/test_problem_set_assignment.py -v`
Expected: FAIL — `TypeError` for the unexpected `problems_required`.

- [ ] **Step 3: Implement the creation path and the validation**

`create_assignment` takes `problems_required`; the form passes it; invalid values are a 422 form error that keeps what was typed, as `assignment_create` already does. The chapter picker lists problem-set packs available to the section beside the existing company picker.

The CSV and the mastery view are expected to need no code change. If the test above fails, the
finding is theirs and the fix belongs in this task — not a note for later.

- [ ] **Step 4: Hide the blocks that do not apply**

In `diagnostics.html` and `progress.html`, branch on the assignment's pack kind. Hide, do not blank: a section that renders empty reads as an outage.

- [ ] **Step 5: Run the staff suites**

Run: `.venv/bin/python -m pytest tests/integration/test_problem_set_assignment.py tests/integration/test_scoped_console.py tests/integration/test_staff_console.py tests/integration/test_assignment_setup.py tests/guards -q`
Expected: PASS. `diagnostics.html` and `assignment_new.html` are shared, so a template error breaks the console for every teacher.

- [ ] **Step 6: Commit**

```bash
git add originalentry/staff/views.py originalentry/services/assignments.py \
        originalentry/templates/staff/ tests/integration/test_problem_set_assignment.py
git commit -m "feat: assign a chapter, and a console that makes sense for one"
```

---

## After the last task

1. Run the full suite from the repository root: `.venv/bin/python -m pytest`. About 56 minutes, against the development branch, nothing else touching it.
2. **Then, and only with the owner's explicit consent, apply the migration to production.** It adds four `content_pack` columns, `assignment.problems_required`, `problem_attempt`, and backfills `kind` on every existing pack. The backfill is the part to say out loud: every existing row becomes `practice_set`.
3. The chapter file import to production is a separate consented step again, since `flask problems import` writes content.

## What this plan does not do

From the spec's non-goals, repeated so an implementer does not drift: only journal entries; one variant per problem set; one authoring path (no spreadsheet, no generator route, no in-app screen); no AI; no system-allocated problem pools; no per-problem mastery dimension; and no live earned-mark count on the student's problems list.
