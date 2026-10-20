# Concept tagging and the mastery view — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the Diagnostics screen a ranked mastery-by-concept block and a most-common-mistakes block, so an instructor can see what to reteach and who to pull aside.

**Architecture:** A `concept` table and a `concept_tag` table map the two artifacts that already carry evidence — rubric component keys and error-signature keys — onto one app-wide vocabulary. A new `services/mastery.py` turns an assignment into a report: process concepts as a share of marks (from `final_marks`, over submitted work), topic concepts as counts of detected misconceptions (regrouping the signature counts `services/diagnostics.py` already produces). The existing diagnostics view and template gain the two blocks and one drill-down route.

**Tech Stack:** Flask 3.1, SQLAlchemy 2.0, Flask-Migrate/Alembic, Jinja2, Tailwind v4 (prebuilt), pytest against Postgres.

**Spec:** `docs/superpowers/specs/2026-10-19-concept-tagging-and-mastery-design.md`

## Global Constraints

Copied from the spec. Every task's requirements implicitly include these.

- **Teachers see their own sections; admins see everything.** Both new routes go through `_assignment_or_404`, which calls `may_see_section`.
- **`abort(404)`, never 403.** A refusal must not confirm the page exists.
- **The CSP forbids inline styles.** `security.py:18` is `style-src 'self' 'nonce-{nonce}'` with no `unsafe-inline`. Bars are `<meter>` elements, as `templates/staff/diagnostics.html` already does and says in its header comment. A `style=` attribute renders unstyled in production with no error.
- **Tailwind v4 emits nothing for a utility it has not scanned**, silently. Every class used must already be present in `originalentry/static/dist/app.css`; verify before using one.
- **Marks come from `services/grades.final_marks(session, workspace)`**, never the raw engine result, so mastery agrees with the CSV on the same screen.
- **The population is submitted work**: `grades.submission_status(session, workspace)` in `{grades.SUBMITTED, grades.SUBMITTED_LATE}` and `archived_at is None`. Not `status == "submitted"`, not `submitted_at is not None`.
- **Topic concepts get counts, never percentages.** `signatures.detect` returns nothing for empty books, so absence of a signature is not evidence of understanding.
- **Nothing in `originalentry/grading/` or `services/grades.py` may import `models.concepts` or `services.mastery`.** Tagging must not be able to change a score.
- **Migration head is `f4a9c0d71e22`** (`audit_log`). The new revision chains from it.
- **`ruff check originalentry tests` must stay clean** — 6 pre-existing findings in untouched files.
- **Tests run against a shared Postgres holding real student work.** The full suite takes ~50 minutes and two concurrent runs deadlock. Run the files you are working on; never run `flask packs import`, `flask packs migrate` or `flask grade`.

## Review Focus

Input classes the spec implies that no task's happy path exercises. Each has a test in the task that owns the code.

1. **An assignment with nothing submitted yet.** A brand-new assignment has no population: the report must render with zeroed blocks and no callout, not divide by zero. (Task 2)
2. **An assignment whose pack has no tagged component.** Block A is empty: the screen must say so rather than show an empty ranked list under a callout naming nothing. (Task 4)
3. **A `concept_key` in the URL that does not exist, or is retired.** Must `abort(404)`, not render an empty page that looks valid. (Task 3)
4. **A component zeroed by a grade override.** Mastery must move, because `final_marks` applies overrides and the CSV beside it already does. (Task 2)
5. **A choice assignment, where one cohort spans several pack versions.** Block A still pools (component keys are global); Block B counts only what each student's own variant could trigger. Neither may raise on `fixed_pack_version_id is None`. (Task 3)

---

## File Structure

| File | Responsibility |
| --- | --- |
| `originalentry/models/concepts.py` (create) | `Concept`, `ConceptTag`. New module rather than growing `people.py` or `content.py`. |
| `originalentry/models/__init__.py` (modify) | Export both, following the existing alphabetical-within-group pattern. |
| `migrations/versions/<rev>_concepts.py` (create) | Both tables; seeds the vocabulary and every tag. |
| `originalentry/services/mastery.py` (create) | All arithmetic and grouping. No Flask imports. |
| `originalentry/staff/views.py` (modify) | `diagnostics` passes the report; one new route. |
| `originalentry/templates/staff/diagnostics.html` (modify) | The two blocks and the callout. |
| `originalentry/templates/staff/concept.html` (create) | The drill-down. |
| `tests/guards/test_concept_tags.py` (create) | Every seeded tag resolves to a real artifact key. |
| `tests/guards/test_import_boundaries.py` (modify) | Grading may not import concepts or mastery. |
| `tests/guards/test_scoping.py` (modify) | Both routes into the matrix. |
| `tests/unit/test_mastery.py` (create) | Arithmetic and grouping, no database. |
| `tests/integration/test_mastery_screen.py` (create) | Population, overrides, scoping, drill-down. |

---

### Task 1: The vocabulary, its tables, and the guards that keep it honest

**Files:**
- Create: `originalentry/models/concepts.py`
- Modify: `originalentry/models/__init__.py`
- Create: `migrations/versions/<rev>_concepts.py`
- Create: `tests/guards/test_concept_tags.py`
- Modify: `tests/guards/test_import_boundaries.py`

**Interfaces:**
- Consumes: `packs.validate.KNOWN_COMPONENTS` (frozenset of ten component keys).
- Produces: `models.Concept` with columns `id`, `key: str(40) unique`, `label: str(120)`, `group: str(10)`, `ordinal: int`, `retired_at: datetime | None`; `models.ConceptTag` with `id`, `concept_id: FK(concept.id)`, `artifact_kind: str(10)`, `artifact_key: str(60)`, and `UniqueConstraint("artifact_kind", "artifact_key")`. Group values are the literals `"process"` and `"topic"`.

- [ ] **Step 1: Write the failing guard**

Create `tests/guards/test_concept_tags.py`. `pytestmark = pytest.mark.db`.

```python
def test_every_component_tag_names_a_real_component(session):
    """A renamed component key must fail here, not quietly untag itself."""
    keys = set(session.scalars(db.select(ConceptTag.artifact_key).filter_by(
        artifact_kind="component")).all())
    assert keys <= KNOWN_COMPONENTS, f"tags naming no component: {sorted(keys - KNOWN_COMPONENTS)}"


def test_every_signature_tag_names_a_signature_some_pack_declares(session):
    """Checked against the pack sources on disk, NOT against imported rubrics: four component
    keys appear in no pack, so a guard written against imports fails on day one."""
    declared = _signature_keys_on_disk()          # union over packs/*/source.json
    keys = set(session.scalars(db.select(ConceptTag.artifact_key).filter_by(
        artifact_kind="signature")).all())
    assert keys <= declared, f"tags naming no signature: {sorted(keys - declared)}"


def test_every_tag_resolves_to_a_concept(session):
    orphans = session.scalars(db.select(ConceptTag).outerjoin(Concept).filter(
        Concept.id.is_(None))).all()
    assert not orphans


def test_every_component_key_is_tagged(session):
    """Untagged is a transitional row on the screen, not a permanent state for a known key."""
    tagged = set(session.scalars(db.select(ConceptTag.artifact_key).filter_by(
        artifact_kind="component")).all())
    assert KNOWN_COMPONENTS <= tagged, f"untagged: {sorted(KNOWN_COMPONENTS - tagged)}"
```

Write `_signature_keys_on_disk()` in the same file: walk `packs/*/source.json`, collect every `error_signatures[*].key` at any depth.

- [ ] **Step 2: Extend the import-boundary guard**

In `tests/guards/test_import_boundaries.py`, which already walks the AST for forbidden imports, add a second test asserting no module under `originalentry/grading/` and not `originalentry/services/grades.py` imports `originalentry.models.concepts` or `originalentry.services.mastery`. Reuse the existing `_imported_modules` helper.

- [ ] **Step 3: Run both to verify they fail**

Run: `.venv/bin/python -m pytest tests/guards/test_concept_tags.py tests/guards/test_import_boundaries.py -v`
Expected: the four tag tests FAIL on `ImportError` / missing table; the boundary test PASSES (nothing imports it yet — it is a regression guard, and that is the correct state).

- [ ] **Step 4: Write the models**

`originalentry/models/concepts.py` with the two classes from the Interfaces block. Follow `models/people.py`'s style: `Mapped[...]` / `mapped_column`, a docstring on each class saying what it is for, `Index` in `__table_args__` where a query needs one (`concept_tag.artifact_key` is looked up by key on every report, so index it).

Export both from `models/__init__.py` and add to `__all__`.

- [ ] **Step 5: Write the migration**

`down_revision = 'f4a9c0d71e22'`. Follow `migrations/versions/f4a9c0d71e22_audit_log.py` for layout. Create both tables, then seed in the same revision with `op.bulk_insert`:

- 17 concepts, from the spec's two tables (§The concept list), `group` set to `"process"` or `"topic"`, `ordinal` ascending within each group in the order the spec lists them.
- One component tag per key in `KNOWN_COMPONENTS` (ten rows), mapped as the spec's process table shows.
- One signature tag per key in the spec's topic table (thirteen rows).

The seed values are the spec's; copy them, do not re-derive them from the packs.

`downgrade()` drops both tables.

- [ ] **Step 6: Apply it and run the guards**

Run: `FLASK_APP=originalentry.app:create_app ORIGINALENTRY_USE_DIRECT_DB=1 .venv/bin/python -m flask db upgrade`

**This writes to the shared production database. Get the owner's explicit consent first and report what it prints.** Plain `.venv/bin/python -m flask db ...` fails with `No such command 'db'` without `FLASK_APP`; the direct-DB flag bypasses the pooler for DDL, as the `Procfile` release phase does.

Run: `.venv/bin/python -m pytest tests/guards -q`
Expected: PASS, including `test_schema_drift.py` — which is also the proof the models and the migration agree.

- [ ] **Step 7: Commit**

```bash
git add originalentry/models/concepts.py originalentry/models/__init__.py \
        migrations/versions/*_concepts.py tests/guards/test_concept_tags.py \
        tests/guards/test_import_boundaries.py
git commit -m "feat: one concept vocabulary, and the tags that attach it"
```

---

### Task 2: Block A — mastery as a share of marks

**Files:**
- Create: `originalentry/services/mastery.py`
- Create: `tests/unit/test_mastery.py`
- Create: `tests/integration/test_mastery_screen.py` (population and override cases only; the screen arrives in Task 4)

**Interfaces:**
- Consumes: `models.Concept`, `models.ConceptTag` (Task 1); `services.grades.final_marks`, `services.grades.submission_status`, `services.grades.SUBMITTED`, `services.grades.SUBMITTED_LATE`; `grades.FinalMarks.components` is a tuple of `ComponentMark(key, label, points, max_points, overridden, reason)`.
- Produces:
  ```python
  SUPPORT_THRESHOLD = 70.0   # percent; a starting guess, not a kill switch

  @dataclass(frozen=True)
  class ConceptMastery:
      key: str            # concept key, or "untagged"
      label: str
      points: float
      max_points: float
      @property
      def percent(self) -> float   # 0.0 when max_points is 0

  @dataclass(frozen=True)
  class MasteryReport:
      submitted: int
      total: int
      needs_support: int
      concepts: tuple[ConceptMastery, ...]       # weakest first; "untagged" always last
      weakest: ConceptMastery | None             # None when concepts is empty

  def assignment_mastery(session, assignment) -> MasteryReport
  ```
  Task 3 adds two more fields to `MasteryReport`; Task 4 reads all of them.

- [ ] **Step 1: Write the failing unit tests**

Create `tests/unit/test_mastery.py`. No database: build `FinalMarks` objects directly and call the pure helper this task extracts for the arithmetic.

```python
def test_pools_marks_across_students_rather_than_averaging_percentages():
    """One student scoring 1/10 and one scoring 9/10 is 50%, not the mean of 10% and 90% --
    which agree here, so use 1/10 and 18/20 where they do not."""

def test_a_concept_with_no_tagged_component_is_absent_not_zero():
    """A dormant concept must not read as total failure."""

def test_components_with_no_concept_pool_into_one_untagged_row_last():

def test_the_weakest_concept_is_the_lowest_percentage_not_the_lowest_points():
```

These call `mastery.rank_concepts(marks: list[FinalMarks], tags: dict[str, tuple[str, str]]) -> tuple[ConceptMastery, ...]`, the pure helper `assignment_mastery` wraps. `tags` maps a component key to `(concept_key, concept_label)`. Extracting it is what lets the arithmetic be tested without a session.

- [ ] **Step 2: Write the failing integration tests**

In `tests/integration/test_mastery_screen.py`, `pytestmark = pytest.mark.db`. Build fixtures on `tests/scoping_world.py`'s `own_section_world` and `staff_account`.

```python
def test_only_submitted_work_counts(session, ...):
    """An open workspace contributes 0/full to every concept it touches, because max_points is
    always the pack's full weight -- so including it would drag every percentage toward zero."""

def test_a_reopened_workspace_still_counts(session, ...):
    """submission_status still reports it submitted. This is the case where the three candidate
    definitions of "submitted" disagree, which is why the population names the function."""

def test_an_assignment_with_nothing_submitted_reports_zeroes_and_no_weakest(session, ...):
    """Review Focus 1. A brand-new assignment must render, not divide by zero."""

def test_an_override_moves_the_concept_it_belongs_to(session, ...):
    """Review Focus 4. final_marks applies overrides and the CSV on this screen already does."""

def test_needs_support_counts_students_below_the_threshold(session, ...):
```

- [ ] **Step 3: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_mastery.py tests/integration/test_mastery_screen.py -v`
Expected: FAIL — `ModuleNotFoundError: originalentry.services.mastery`.

- [ ] **Step 4: Implement `services/mastery.py`**

`rank_concepts(...)` as named in Step 1, and `assignment_mastery(session, assignment) -> MasteryReport` around it. One query for the workspaces, one for the tag map (`artifact_kind == "component"`, joined to `Concept`, excluding `retired_at is not None`), then `final_marks` per workspace. No Flask imports in this module.

Population: workspaces of the assignment with `archived_at is None` whose `submission_status` is `SUBMITTED` or `SUBMITTED_LATE`. `total` is every non-archived workspace; `submitted` is the population size.

- [ ] **Step 5: Run them to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_mastery.py tests/integration/test_mastery_screen.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add originalentry/services/mastery.py tests/unit/test_mastery.py \
        tests/integration/test_mastery_screen.py
git commit -m "feat: mastery by concept, over submitted work and final marks"
```

---

### Task 3: Block B — the mistakes, and the drill-down data

**Files:**
- Modify: `originalentry/services/mastery.py`
- Modify: `tests/unit/test_mastery.py`
- Modify: `tests/integration/test_mastery_screen.py`

**Interfaces:**
- Consumes: `services.diagnostics.cohort_diagnostics(session, assignment) -> CohortDiagnostics`, whose `.signatures` is a tuple of `SignatureCount(key, label, students, possible)` already ranked by `students` descending; `.graded` and `.total` are ints.
- Produces:
  ```python
  @dataclass(frozen=True)
  class ConceptMistakes:
      key: str
      label: str
      mistakes: tuple[SignatureCount, ...]   # reused from services.diagnostics, ranked

  @dataclass(frozen=True)
  class StudentRef:
      workspace_public_id: str
      name: str

  @dataclass(frozen=True)
  class StudentMark:
      student: StudentRef
      points: float
      max_points: float

  @dataclass(frozen=True)
  class SignatureStudents:
      signature_key: str
      label: str
      students: tuple[StudentRef, ...]

  @dataclass(frozen=True)
  class ConceptDetail:
      key: str
      label: str
      group: str                                # "process" | "topic"
      marks: tuple[StudentMark, ...]            # process only: lowest first
      mistakes: tuple[SignatureStudents, ...]   # topic only: who triggered each signature
      clear: tuple[StudentRef, ...]             # topic only: nothing detected, which is NOT
                                                # evidence of understanding -- no marks to show,
                                                # which is why this is StudentRef not StudentMark

  def concept_detail(session, assignment, concept_key) -> ConceptDetail   # raises LookupError
  ```
  `MasteryReport` gains `mistakes: tuple[ConceptMistakes, ...]` and `top_mistake: SignatureCount | None`.

**Note on ranking.** A concept group carries no aggregate student count: summing its signatures would double-count a student who triggered two. Concept groups are ranked by their highest single signature count, and the counts live on the signatures. `top_mistake` is the single highest count across all groups.

**Note on population.** Block B reuses `cohort_diagnostics`, whose population is every non-archived workspace with a run — broader than Block A's submitted-only. This is deliberate and must be surfaced on the screen (Task 4): a count does not dilute the way a rate does, so there is no reason to narrow it, and narrowing would change an existing section's numbers.

- [ ] **Step 1: Write the failing tests**

Unit (no database), in `tests/unit/test_mastery.py`:

```python
def test_signatures_group_under_their_concept_and_untagged_ones_are_dropped():
    """A signature with no tag is not a mistake we can name a concept for."""

def test_concept_groups_rank_by_their_highest_single_count_not_a_sum():
    """Summing would double-count a student who triggered two signatures in one concept."""

def test_top_mistake_is_the_highest_count_across_every_group():
```

Integration, in `tests/integration/test_mastery_screen.py`:

```python
def test_concept_detail_for_a_process_concept_lists_students_lowest_first(session, ...):

def test_concept_detail_for_a_topic_concept_groups_students_under_each_signature(session, ...):

def test_concept_detail_lists_students_with_nothing_detected_separately(session, ...):
    """Absence of a signature is not evidence of understanding; they are listed, not counted."""

def test_concept_detail_raises_for_an_unknown_or_retired_concept(session, ...):
    """Review Focus 3. The view turns LookupError into abort(404)."""

def test_a_choice_assignment_does_not_raise(session, ...):
    """Review Focus 5. fixed_pack_version_id is None and diagnostics._keys_by_variant returns {}."""
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_mastery.py tests/integration/test_mastery_screen.py -v`
Expected: FAIL — `ImportError: cannot import name 'concept_detail'`.

- [ ] **Step 3: Implement the grouping and the detail**

Add to `services/mastery.py`. The grouping is a join of `cohort_diagnostics(...).signatures` against the signature tag map. `concept_detail` raises `LookupError` for a key with no live `Concept`, and branches on `group` for which half it fills.

- [ ] **Step 4: Run them to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_mastery.py tests/integration/test_mastery_screen.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add originalentry/services/mastery.py tests/unit/test_mastery.py \
        tests/integration/test_mastery_screen.py
git commit -m "feat: the mistakes block, grouped by concept, and the drill-down data"
```

---

### Task 4: The screen and the drill-down route

**Files:**
- Modify: `originalentry/staff/views.py` — `diagnostics` (currently at `:451-460`) and one new route beside it
- Modify: `originalentry/templates/staff/diagnostics.html`
- Create: `originalentry/templates/staff/concept.html`
- Modify: `tests/guards/test_scoping.py`
- Modify: `tests/integration/test_mastery_screen.py`

**Interfaces:**
- Consumes: `mastery.assignment_mastery`, `mastery.concept_detail`, `mastery.SUPPORT_THRESHOLD` (Tasks 2-3).
- Produces: endpoint `staff.concept_detail` at `GET /staff/diagnostics/<assignment>/concept/<concept_key>`.

- [ ] **Step 1: Write the failing tests**

In `tests/integration/test_mastery_screen.py`:

```python
def test_a_teacher_sees_mastery_for_their_own_section(client, ...):

def test_a_teacher_is_refused_another_sections_mastery(client, ...):
    """404, never 403."""

def test_an_admin_sees_both(client, ...):

def test_an_unknown_concept_key_is_a_404(client, ...):
    """Review Focus 3, through the route."""

def test_an_assignment_with_no_tagged_component_says_so(client, ...):
    """Review Focus 2. An empty Block A must explain itself, not sit under a callout that names
    nothing."""

def test_the_two_blocks_name_their_populations(client, ...):
    """Block A is submitted work; Block B is everything graded. Different questions, each stated,
    so neither contradicts the other or the CSV."""
```

In `tests/guards/test_scoping.py`, add `staff.concept_detail` to the scoped routes. It takes an `<assignment>`, so `test_every_scoped_console_route_goes_through_one_of_the_two_lookups` will require `_assignment_or_404`; add `concept_key` to `PLACEHOLDERS`.

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/integration/test_mastery_screen.py tests/guards/test_scoping.py -v`
Expected: FAIL — `BuildError` for `staff.concept_detail`, and the guard matrix failing on an exempt name that matches no route.

- [ ] **Step 3: Add the route and pass the report**

`diagnostics` gains `mastery=assignment_mastery(db.session, found)`. The new route carries `@staff_view`, calls `_assignment_or_404`, and turns `LookupError` into `abort(404)`.

- [ ] **Step 4: Write the template sections**

In `diagnostics.html`, above the existing sections: the context line, the callout, Block A, Block B. In `concept.html`, the two shapes.

Verify every utility class is already in `static/dist/app.css` before using it — Tailwind v4 emits nothing for an unscanned class and reports no error. Bars are `<meter>`, as this template's own header comment explains; the threshold distinction goes on the row, not the bar fill.

Exact callout copy:

> **Review {{ weakest.label }} before the next assignment.** The most common mistake was {{ top_mistake.label }} ({{ top_mistake.students }} students).

Omit each clause when its value is `None`.

- [ ] **Step 5: Run them to verify they pass**

Run: `.venv/bin/python -m pytest tests/integration/test_mastery_screen.py tests/guards -q`
Expected: PASS.

- [ ] **Step 6: Check the whole console still renders**

Run: `.venv/bin/python -m pytest tests/integration/test_scoped_console.py tests/integration/test_staff_console.py tests/guards -q`
Expected: PASS. The diagnostics template is shared, so a template error here breaks the console for every teacher.

- [ ] **Step 7: Commit**

```bash
git add originalentry/staff/views.py originalentry/templates/staff/diagnostics.html \
        originalentry/templates/staff/concept.html tests/guards/test_scoping.py \
        tests/integration/test_mastery_screen.py
git commit -m "feat: the Diagnostics screen says what to reteach"
```

---

## After the last task

Run the full suite once, from the repository root: `.venv/bin/python -m pytest`. It takes about 50 minutes and nothing else may run against the database while it does. The diagnostics view is on a shared template and the new tables are in the shared schema, so this is the run that proves nothing else moved.

## Expect five rows, not eight

Against the packs as they stand, Block A renders **five concepts plus Untagged**: `triage`,
`journal_selection`, `entry_accuracy`, `posting_completeness` and `subsidiary_agreement` are the
only component keys any real pack uses. `adjustment_amounts` appears only in `riverbend-demo`, and
`adjustment_form`, `statements_structure`, `statements_figures` and `closing` appear in no pack at
all — their concepts are seeded so a future pack lights them up without a migration.

This is expected, not a bug to chase. Block B is fully populated: ten concepts over thirteen
signature keys across three real packs. The spec's *The five-row reality* explains why it is worth
shipping anyway.

## What this plan does not do

From the spec's non-goals, repeated so an implementer does not drift: no new assignment types, no LMS sync, no AI, no term-to-date mastery, no student-facing view, no checkpoint tagging, no tagging screen, and no percentage for a topic concept.
