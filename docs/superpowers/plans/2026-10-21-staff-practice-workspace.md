# A teacher can work their own assignment — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A teacher opens one action on their own assignment and gets a real, writable workspace that behaves exactly as a student's — and that no class-level number, export or grading run can see.

**Architecture:** One boolean on `Workspace` says a row is a teacher's practice copy. Two things read it. `is_own_practice(workspace, actor)` is the single definition of "this is my own practice copy", called by *both* write gates — `decorators.workspace_view` and `services.write._check_gates` — which today disagree about who may write. And `class_workspaces(session, assignment)` is the single query for an assignment's class-facing workspaces, which every cohort read goes through, enforced by a guard that fails if any module queries workspaces by assignment without it.

**Tech Stack:** Flask 3.1, SQLAlchemy 2.0, Flask-Migrate/Alembic, Jinja2, Tailwind v4 (prebuilt), pytest against Postgres.

**Spec:** `docs/superpowers/specs/2026-10-21-staff-practice-workspace-design.md`

## Global Constraints

Copied from the spec. Every task's requirements implicitly include these.

- **There are TWO independent write gates.** `decorators.py:157` sets `g.read_only`, which the chapter-problem routes consult via `_guard_writable`. Every practice-set write goes through `services.write.workspace_write`, whose `_check_gates` (`write.py:47`) independently refuses `actor.role != ROLE_STUDENT or actor.id != workspace.student_id`. **Relaxing only the decorator makes problem sets writable and leaves every practice-set write refused.**
- **`_check_gates` is where the deadline and variant rules live**, not `workspace_view`: `status == "submitted"`, `variant_id is None` (`messages.WAITING_FOR_VARIANT`), and `accommodations.close_for`.
- **A teacher's practice work must never reach a class-level number**, export, or `GradeRun` beside real students. "This is the failure to design against; everything else is recoverable."
- **A teacher must not be able to write to a student's workspace.** Relaxing read-only for a practice copy must not relax it anywhere else.
- **Only the owning teacher can see a practice copy** — not co-teachers, not admins. `staff/views.py:226 _workspace_or_404` scopes by assignment and section only and feeds six routes, so this is not enforceable from `workspace_view` alone.
- **A practice copy ignores** the prerequisite chain, `opens_at`, `due_at`, the late policy, and `marks_released_at`.
- **`services/purge.py` must NOT exclude practice copies** — retention deletion must reach every row or it orphans records behind foreign keys.
- **No second code path for the student screens.** The copy is a real workspace; the fidelity comes from being the same code.
- **`abort(404)`, never 403**, for a workspace the caller may not see.
- **Amounts are cents.** The CSP forbids inline styles (`security.py:18`): no inline `style`. **Tailwind v4 emits nothing for an unscanned utility, silently** — verify each class against `static/dist/app.css`, and note CSS escapes `.`, `/` and `:`, so check the escaped form.
- **`ruff check originalentry tests` must stay clean** — 6 pre-existing findings in untouched files as of `ad4eedc`.
- **Migration head is `b5f08c2a91d6`.** New revisions chain from it.
- **The suite runs against the Neon development branch** when `TEST_DATABASE_URL` is set. Two concurrent runs deadlock; the full suite is ~65 minutes. Apply migrations there first; production is a separate, consented step.
- **Do not edit source files while a test run is in flight** — `inspect.getsource` guards read the file at assertion time while the imported module holds the old line numbers, which produces false failures.

## Review Focus

Input classes the spec implies that no happy path exercises. Each has a test in the task that owns it.

1. **A practice-set write by the practice owner.** Entries, dispositions, posting, statements, submit — all through `workspace_write`. If only the decorator is relaxed these stay refused, and the feature appears to work because chapter problems do. (Task 1)
2. **A co-teacher or an admin holding a practice copy's public id.** Owner-only has to hold at `_workspace_or_404`, which feeds `grading_detail`, `workspace_archive`, `workspace_reopen`, `grading_override`, `grading_comment` and `progress_variant`. (Task 4)
3. **A manual-variant or student-choice assignment.** `variant_for` returns None for `MANUAL`, `_check_gates` then refuses every write with `WAITING_FOR_VARIANT`, and the only hand-out UI is excluded from practice copies — an unwritable copy with nothing on screen to fix it. (Task 3)
4. **Round-robin after a practice copy exists.** `assignments.py:312` counts live workspaces, so a practice copy shifts which variant the *next student* is handed. A correctness bug, not cosmetics. (Task 2)
5. **An account that was a student first, later promoted to staff.** `open_workspace` returns any existing live workspace unchanged, so their old unflagged student work would be handed back as "your practice copy" — read-only, no banner, and the unique index blocks opening a real one beside it. (Task 3)

---

## File Structure

| File | Responsibility |
| --- | --- |
| `originalentry/models/work.py` (modify) | `Workspace.staff_practice` |
| `migrations/versions/<rev>_staff_practice.py` (create) | The column, defaulted false |
| `originalentry/workspaces.py` (create) | `is_own_practice` and `class_workspaces` — the two rules, in one module both the decorator and the services may import without a cycle |
| `originalentry/decorators.py` (modify) | `g.read_only` consults `is_own_practice` |
| `originalentry/services/write.py` (modify) | `_check_gates` consults `is_own_practice`; a practice owner skips the role check and the deadline |
| `originalentry/services/practice.py` (create) | Open, resume and restart a practice copy, and the refusals |
| `originalentry/staff/views.py` (modify) | The console actions, owner-only in `_workspace_or_404`, the cohort reads routed through the chokepoint |
| `originalentry/services/{diagnostics,mastery,progress,marks_export,grades,assignments}.py` (modify) | Cohort reads routed through the chokepoint |
| `originalentry/services/audit.py` (modify) | Practice traffic stays out of the durable trail |
| `originalentry/packs/migrate.py` (modify) | A migration archives practice copies |
| `originalentry/templates/layouts/workspace.html` (modify) | The standing banner |
| `originalentry/templates/staff/progress.html` (modify) | The console actions |
| `tests/guards/test_practice_chokepoint.py` (create) | Every cohort read goes through `class_workspaces` |

---

### Task 1: The flag, and one definition of who may write

**Files:**
- Modify: `originalentry/models/work.py`, `originalentry/decorators.py`, `originalentry/services/write.py`
- Create: `originalentry/workspaces.py`, `migrations/versions/<rev>_staff_practice.py`
- Test: `tests/integration/test_practice_write_gates.py`

**Interfaces:**
- Produces: `Workspace.staff_practice: bool` (default False, server default false); `workspaces.is_own_practice(workspace, actor) -> bool` — True only when `workspace.staff_practice` and `actor is not None` and `actor.id == workspace.student_id`.
- Consumes: `models.ROLE_STUDENT`, `messages.READ_ONLY_SUBMITTED`, `messages.WAITING_FOR_VARIANT`, `accommodations.close_for`.

**Why a new module.** `decorators.py` and `services/write.py` both need the rule, and `services/write.py` already avoids importing `accommodations` at module level to dodge a cycle. A leaf module with no app imports is the safe home.

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_practice_write_gates.py`, `pytestmark = pytest.mark.db`. Fixtures: a teacher with a `SectionStaff` row, a student, an assignment on `testco_alpha`, the student's workspace, and the teacher's practice workspace (`staff_practice=True`, `student_id=teacher.id`).

```python
def test_a_teacher_may_write_to_their_own_practice_copy_through_the_entry_path(session, teacher, practice):
    """Review Focus 1, and the whole point: this is the gate the decorator does not control.
    Every practice-set write -- entries, dispositions, posting, statements, submit -- goes
    through workspace_write, whose _check_gates refuses any non-student actor."""
    record_entry_through(workspace_write, practice, actor=teacher)   # must not raise

def test_a_teacher_may_not_write_to_a_students_workspace(session, teacher, student_workspace):
    """The anti-goal. Relaxing the gate for a practice copy must not relax it for anything else."""
    with pytest.raises(WriteRefused):
        ...

def test_a_teacher_may_not_write_to_another_teachers_practice_copy(session, other_teacher, practice):

def test_a_student_is_unaffected(session, student, student_workspace):
    """Guards the change from the inside: the ordinary path must behave exactly as before."""

def test_a_practice_copy_ignores_the_deadline(session, teacher, practice, assignment):
    """_check_gates refuses on accommodations.close_for. A teacher preparing next term's
    assignment works a copy whose deadline has not opened, or has passed."""

def test_a_practice_copy_is_still_read_only_once_submitted(session, teacher, practice):
    """Submitting is part of the student experience they are checking, and a submitted copy
    reads as a student's does. Start over is how they get a writable one back."""

def test_g_read_only_is_false_on_a_practice_copy_and_true_on_a_students(client, teacher, practice, student_workspace):
    """The other gate. Both must agree, or the problem screens and the journal screens disagree
    about whether the same person may type."""

def test_neither_gate_decides_it_alone(app):
    """Source inspection: both decorators.workspace_view and write._check_gates must name
    is_own_practice. One definition, two callers -- a second definition is how they drift."""

def test_a_practice_copy_works_on_a_chapter_problem_set(client, teacher, problem_practice):
    """"Both kinds" as an executable claim, half one. The problem routes gate on g.read_only, so
    this half passes on the decorator change alone -- which is exactly why the other half needs
    its own test."""
    # submit an attempt and reveal, through student.problem_submit and student.problem_reveal

def test_a_practice_copy_works_on_a_full_practice_set(client, teacher, practice):
    """And half two, through workspace_write. These two tests failing differently is the signal
    that one gate was changed and the other was not."""
    # record an entry, post it, and submit, through the journal routes

def test_the_problem_set_fence_still_applies_to_a_practice_copy(client, teacher, problem_practice):
    """The two features meet here. decorators._fence keys on the pack's kind, not on who owns the
    workspace, so a teacher practising a chapter must still get 404 on journals, ledgers,
    statements, the trial balance, checkpoints and the print record -- and the problem routes must
    still 404 on their practice copy of a practice set."""
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/integration/test_practice_write_gates.py -v`
Expected: FAIL — `ImportError` for `originalentry.workspaces`.

- [ ] **Step 3: Add the column, the module and the migration**

`Workspace.staff_practice`, `is_own_practice`, and a migration chaining from `b5f08c2a91d6` adding the column with a server default of false and `NOT NULL`. Apply it to the development branch.

- [ ] **Step 4: Make both gates consult it**

`decorators.py:157` — the `is_staff` term becomes conditional on `not is_own_practice(ws, current_user)`; the archived and submitted terms are untouched. `write.py:_check_gates` — the role/ownership refusal admits a practice owner, and `close_for` is skipped for one; `submitted` and `variant_id is None` still refuse.

- [ ] **Step 5: Run them to verify they pass**

Run: `.venv/bin/python -m pytest tests/integration/test_practice_write_gates.py tests/integration/test_save_protocol.py tests/integration/test_submit_readiness.py tests/guards -q`
Expected: PASS. The two existing suites are the proof a student's path did not move.

- [ ] **Step 6: Commit**

```bash
git add originalentry/models/work.py originalentry/workspaces.py originalentry/decorators.py \
        originalentry/services/write.py migrations/versions/*_staff_practice.py \
        tests/integration/test_practice_write_gates.py
git commit -m "feat: a practice copy its owner may write to, agreed by both gates"
```

---

### Task 2: The chokepoint, and the guard that keeps it honest

**Files:**
- Modify: `originalentry/workspaces.py`, `originalentry/services/{diagnostics,mastery,progress,marks_export,grades,assignments}.py`, `originalentry/staff/views.py`
- Create: `tests/guards/test_practice_chokepoint.py`
- Test: `tests/integration/test_practice_exclusion.py`

**Interfaces:**
- Produces: `workspaces.class_workspaces(session, assignment)` — the live, non-practice workspaces of one assignment, returned as a list; and `workspaces.class_workspace_ids(session, assignment)` where a caller needs ids for an `IN` clause.
- Consumes: Task 1's `Workspace.staff_practice`.

**The three query shapes, and which this covers.** Fifteen sites query `Workspace.assignment_id`. Nine are **cohort** reads — `(assignment_id, archived_at IS NULL)` with no `student_id` — and every one must exclude practice copies: `diagnostics.py:181`, `mastery.py:141`, `progress.py:98`, `marks_export.py:23`, `grades.py:214`, `grades.py:233`, `staff/views.py:246` (archived-books list), `staff/views.py:271` (grading roster), `assignments.py:312` (the round-robin count). Four are **per-person** — they also filter `student_id`, so a practice copy only ever matches its own owner and they must be left alone: `student/views.py:252`, `multicompany.py:165`, `assignments.py:250`, `assignments.py:237`. Two are **write paths** and belong to Task 6: `packs/migrate.py:173` and `purge.py:59`.

- [ ] **Step 1: Write the failing guard**

Create `tests/guards/test_practice_chokepoint.py`. This is what makes the exclusion trustworthy rather than nine things somebody remembered.

```python
#: Modules that query workspaces by assignment, and must do it through class_workspaces.
WALKERS = ("services/diagnostics.py", "services/mastery.py", "services/progress.py",
           "services/marks_export.py", "services/grades.py", "services/assignments.py",
           "staff/views.py", "student/views.py", "packs/migrate.py", "services/purge.py")

#: Queries that are not cohort reads, and why. A per-person query filters student_id, so a
#: practice copy only ever matches its owner; the two write paths have their own decisions.
EXEMPT = {
    "services/purge.py": "retention deletion must reach every row or it orphans FK records",
    "packs/migrate.py": "a migration archives practice copies (Task 6), it does not report them",
}

def test_every_cohort_read_goes_through_the_chokepoint():
    """A module that queries Workspace.assignment_id without also filtering student_id is asking
    a class-level question, and a class-level question that sees a practice copy puts a teacher's
    own attempts in a student's gradebook. Source inspection, in the idiom of
    test_scoping.py::test_every_scoped_console_route_goes_through_one_of_the_two_lookups."""

def test_every_exempt_module_really_queries_workspaces():
    """Guards the exemptions: a name here matching no such query stops excusing anything."""

def test_the_walker_list_is_every_module_that_queries_workspaces_by_assignment():
    """A new module shows up here and somebody has to classify it -- the same reason
    test_problem_set_fence pins its practice-only list as a literal."""
```

- [ ] **Step 2: Write the failing exclusion tests**

In `tests/integration/test_practice_exclusion.py`, one per cohort read, against an assignment with one student workspace and one practice copy:

```python
def test_the_progress_table_does_not_list_the_practice_copy(session, world):
def test_the_marks_csv_does_not_carry_the_practice_copy(session, world):
def test_the_cohort_diagnostics_ignore_the_practice_copy(session, world):
def test_the_mastery_view_ignores_the_practice_copy(session, world):
    """Including it would move the submitted rate and every concept's share of marks."""
def test_the_cohort_grading_run_skips_the_practice_copy(session, world):
    """No GradeRun for it from grade_section, so it never sits in the class's grading records."""
def test_the_grading_roster_does_not_list_the_practice_copy(session, world):
def test_the_archived_books_list_does_not_list_the_practice_copy(session, world):
def test_the_round_robin_count_ignores_the_practice_copy(session, world):
    """Review Focus 4. assignments.py:312 counts live workspaces, so a practice copy shifts
    which variant the NEXT student is handed -- a correctness bug, not a cosmetic one."""
def test_each_of_these_sees_the_student(session, world):
    """Guards all eight from the inside: excluding everything would pass them."""
def test_a_teacher_still_reaches_their_own_copy(session, world):
    """The per-person queries must NOT exclude. student/views.py:252 is how a teacher gets back
    to it from their own workspace list."""
```

- [ ] **Step 3: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/guards/test_practice_chokepoint.py tests/integration/test_practice_exclusion.py -v`
Expected: FAIL — `ImportError` for `class_workspaces`, and the guard reporting all nine cohort reads.

- [ ] **Step 4: Implement the chokepoint and route the nine sites through it**

`class_workspaces` and `class_workspace_ids` in `workspaces.py`; the nine cohort reads call them. A site that needs extra columns in one query may keep its join and add the practice condition **only** by composing with the chokepoint's filter — not by repeating the condition, which is what the guard forbids.

- [ ] **Step 5: Run the guard, the exclusions, and everything that reads a cohort**

Run: `.venv/bin/python -m pytest tests/guards tests/integration/test_practice_exclusion.py tests/integration/test_diagnostics.py tests/integration/test_scoped_console.py tests/unit/test_mastery.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add originalentry/workspaces.py originalentry/services/ originalentry/staff/views.py \
        tests/guards/test_practice_chokepoint.py tests/integration/test_practice_exclusion.py
git commit -m "feat: one query for an assignment's class-facing workspaces, and a guard"
```

---

### Task 3: Opening, resuming, starting over

**Files:**
- Create: `originalentry/services/practice.py`
- Test: `tests/integration/test_practice_lifecycle.py`

**Interfaces:**
- Produces: `practice.PracticeRefused(Exception)` with a `.reason: str` a screen can print; `practice.open_practice(session, assignment, teacher, *, actor=None) -> Workspace` (resumes an existing live copy, else creates one); `practice.restart_practice(session, assignment, teacher, *, actor=None) -> Workspace`; `practice.practice_copy(session, assignment, teacher) -> Workspace | None`.
- Consumes: Task 1's `staff_practice`; `assignments.variant_for`, `assignments.archive_and_restart(session, workspace, *, reason, actor=None)`.

- [ ] **Step 1: Write the failing tests**

```python
def test_opening_creates_a_practice_copy_pinned_to_the_assignments_version(session, teacher, assignment):
def test_opening_again_resumes_the_same_copy(session, teacher, assignment):
    """A practice set takes hours. A second click must not be a reset."""
def test_restart_archives_the_old_copy_and_opens_a_fresh_one(session, teacher, assignment):
    """Nothing is destroyed, in keeping with how a student's restart works."""
def test_restart_keeps_the_archived_copy_readable(session, teacher, assignment):
def test_a_practice_copy_ignores_the_prerequisite_chain(session, teacher, assignment_with_prerequisite):
    """A teacher must not have to work November to practise December."""
def test_a_practice_copy_ignores_opens_at(session, teacher, future_assignment):
    """Preparing next term's assignment is the main use."""

def test_a_manual_variant_assignment_is_refused_with_a_reason(session, teacher, manual_assignment):
    """Review Focus 3. variant_for returns None for MANUAL, _check_gates then refuses every
    write with WAITING_FOR_VARIANT, and the only hand-out UI excludes practice copies -- so the
    copy would be unwritable with nothing on screen to fix it. Refusing says why instead."""
def test_a_student_choice_assignment_is_refused_with_a_reason(session, teacher, choice_assignment):
    """No single pinned version to copy."""
def test_an_account_with_its_own_student_workspace_is_refused(session, promoted_user, assignment):
    """Review Focus 5. open_workspace returns any existing live workspace unchanged, so a student
    later promoted to instructor would be handed their old UNFLAGGED work as "your practice copy"
    -- read-only, no banner, and uq_workspace_assignment_student_live blocks opening a real one
    beside it. Work done as a student is not converted."""
def test_every_refusal_carries_a_reason_a_screen_can_print(session, teacher):
    """A refusal a template cannot explain is a dead end."""
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/integration/test_practice_lifecycle.py -v`
Expected: FAIL — `ModuleNotFoundError: originalentry.services.practice`.

- [ ] **Step 3: Implement the service**

`open_practice` looks for a live practice copy first and returns it; otherwise refuses the three cases above, then creates a `Workspace` with `staff_practice=True`, `student_id=teacher.id`, the assignment's `fixed_pack_version_id`, and `variant_for`. It does not call `open_workspace` — that function's prerequisite and existing-workspace rules are a student's, not a practice copy's.

- [ ] **Step 4: Run the tests and the existing assignment suites**

Run: `.venv/bin/python -m pytest tests/integration/test_practice_lifecycle.py tests/integration/test_assignment_setup.py tests/integration/test_reopen.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add originalentry/services/practice.py tests/integration/test_practice_lifecycle.py
git commit -m "feat: open, resume and start over a practice copy"
```

---

### Task 4: The screens, and owner-only

**Files:**
- Modify: `originalentry/staff/views.py`, `originalentry/templates/layouts/workspace.html`, `originalentry/templates/staff/progress.html`
- Test: `tests/integration/test_practice_screens.py`

**Interfaces:**
- Consumes: Task 3's `open_practice`, `restart_practice`, `practice_copy`, `PracticeRefused`; Task 1's `is_own_practice`.
- Produces: endpoints `staff.practice_open` and `staff.practice_restart` (both POST).

- [ ] **Step 1: Write the failing tests**

```python
def test_a_co_teacher_cannot_reach_a_colleagues_practice_copy(client, session, world):
    """Review Focus 2. _workspace_or_404 scopes by assignment and section only, and feeds
    grading_detail, workspace_archive, workspace_reopen, grading_override, grading_comment and
    progress_variant. Owner-only is not enforceable from workspace_view alone. 404, never 403."""
def test_an_admin_cannot_reach_a_teachers_practice_copy(client, session, world):
    """Stricter than the existing rule, and deliberately: the point is somewhere unobserved."""
def test_the_owner_can_reach_their_own_through_the_student_screens(client, session, world):
def test_a_teacher_removed_from_the_section_keeps_their_practice_copy(client, session, world):
    """Reaching it needs ownership, not may_see_section."""

def test_every_page_of_a_practice_copy_says_what_it_is(client, session, world):
    """The anti-goal is a teacher mistaking it for a student's. They are the only person who can
    see it and they are told every time they look."""
def test_a_students_workspace_carries_no_such_banner(client, session, world):

def test_the_progress_screen_offers_work_this_myself(client, session, world):
def test_the_action_says_resume_once_a_copy_exists(client, session, world):
    """Silently resuming is how an hour of work looks lost."""
def test_start_over_is_a_separate_action(client, session, world):
def test_a_refused_open_shows_the_reason(client, session, manual_assignment):
    """PracticeRefused's reason reaches the screen rather than a 500."""
def test_the_progress_table_still_does_not_list_the_copy(client, session, world):
    """The console offers the action and excludes the row: both, on one screen."""
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/integration/test_practice_screens.py -v`
Expected: FAIL — `BuildError` for `staff.practice_open`.

- [ ] **Step 3: Enforce owner-only at the lookup**

`_workspace_or_404` refuses a practice copy the caller does not own, with `abort(404)`. Decide per-route which actions a practice copy accepts from its owner; an action whose purpose is one person marking another's work has no meaning where both are the same person, and offering it is worse than refusing it. Record the decision as a literal mapping so it is auditable, not scattered through six routes.

- [ ] **Step 4: Add the routes, the actions and the banner**

The two POST routes; the actions on `staff/progress.html`; the banner in the slot `layouts/workspace.html:79` already uses for the read-only notice. Verify every utility class against the built stylesheet, including its CSS-escaped form.

- [ ] **Step 5: Run the screens and the guards**

Run: `.venv/bin/python -m pytest tests/integration/test_practice_screens.py tests/guards tests/unit/test_web.py -q`
Expected: PASS — including the scoping matrix, which walks every console route.

- [ ] **Step 6: Commit**

```bash
git add originalentry/staff/views.py originalentry/templates/ tests/integration/test_practice_screens.py
git commit -m "feat: work this myself, start over, and a copy only its owner can see"
```

---

### Task 5: Grading one copy

**Files:**
- Modify: `originalentry/staff/views.py`, `originalentry/student/views.py`
- Test: `tests/integration/test_practice_grading.py`

**Interfaces:**
- Consumes: Task 2's chokepoint (which is what already makes `grade_section` skip a practice copy); Task 1's `is_own_practice`.
- Produces: endpoint `staff.practice_grade` (POST).

- [ ] **Step 1: Write the failing tests**

```python
def test_a_teacher_can_grade_their_own_practice_copy(client, session, world):
def test_the_marks_screen_shows_the_mark_without_marks_being_released(client, session, world):
    """student/views.py:1257 gates on assignment.marks_released_at. The marks screen is the one
    screen a teacher most needs to read BEFORE releasing marks to a class."""
def test_a_students_marks_screen_still_waits_for_release(client, session, world):
    """Guards the exemption: it must not relax the gate for anyone else."""
def test_the_evidence_reads_as_a_students_would(client, session, world):
def test_a_teacher_cannot_grade_another_teachers_practice_copy(client, session, world):
def test_a_teacher_cannot_grade_a_students_workspace_through_this_route(client, session, world):
    """The cohort path is how a student's work gets graded, with its own scoping."""
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/integration/test_practice_grading.py -v`
Expected: FAIL — `BuildError` for `staff.practice_grade`.

- [ ] **Step 3: Implement the route and the marks-gate exemption**

`staff.practice_grade` grades one workspace the caller owns. `student/views.py:1257`'s `released` becomes true for a practice copy its owner is viewing.

- [ ] **Step 4: Run the grading suites**

Run: `.venv/bin/python -m pytest tests/integration/test_practice_grading.py tests/integration/test_grade_storage.py tests/integration/test_marks_view.py tests/integration/test_staff_grading.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add originalentry/staff/views.py originalentry/student/views.py tests/integration/test_practice_grading.py
git commit -m "feat: grade your own practice copy and read the marks screen"
```

---

### Task 6: The two paths that are not reports

**Files:**
- Modify: `originalentry/services/audit.py`, `originalentry/packs/migrate.py`
- Test: `tests/unit/test_audit.py`, `tests/integration/test_practice_migration.py`

**Interfaces:**
- Consumes: Task 1's `staff_practice`; Task 2's chokepoint and its exemption list.
- Produces: `should_audit` gains a parameter for "this request is the actor's own practice workspace"; `migrate_assignment` archives practice copies.

**Why these are separate from the chokepoint.** `class_workspaces` answers a reporting question. A migration transforms, and retention deletion must reach every row — a helper that silently excluded practice copies here would leave them pinned to a dead version, or orphan rows behind foreign keys.

- [ ] **Step 1: Write the failing audit tests**

In `tests/unit/test_audit.py` — no database, `should_audit` is a pure decision with its own tests:

```python
def test_a_teachers_own_practice_traffic_is_not_durably_audited():
    """audit.py's own docstring: logging a student's workspace traffic durably "would make a
    purgeable, PII-light record durable and identifying, which the retention split forbids".
    Practice traffic is workspace traffic. Hours of practice would otherwise be one never-purged
    row per request, all labelled student.*, telling admins the copy exists."""

def test_every_other_staff_request_is_still_audited():
    """Guards the carve-out. This is the first per-workspace condition in a function written as a
    pure, shared decision, and the blast radius if it over-matches is the whole trail."""

def test_a_students_own_traffic_is_still_not_audited():
def test_the_auth_blueprint_is_still_always_audited():
```

- [ ] **Step 2: Write the failing migration tests**

```python
def test_a_migration_archives_a_practice_copy(session, world):
    """The owner decision: their throwaway work can never make a class-wide migration
    infeasible, and the copy can never sit on a version no student has."""
def test_a_practice_copys_entries_do_not_make_a_migration_infeasible(session, world):
    """The reason for it. migrate walks workspaces for missing_accounts, missing_parties,
    missing_documents, missing_variants and changed_identity; a throwaway entry referencing an
    account the new version drops would block the whole section."""
def test_the_students_workspaces_still_migrate(session, world):
def test_the_teacher_can_open_a_fresh_copy_on_the_new_version(session, world):
def test_a_dry_run_archives_nothing(session, world):
    """migrate_assignment defaults to dry_run=True and must stay side-effect free."""
```

- [ ] **Step 3: Run both to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_audit.py tests/integration/test_practice_migration.py -v`
Expected: FAIL — the audit tests on the new parameter, the migration tests on the practice copy still being migrated.

- [ ] **Step 4: Implement both**

`should_audit`'s carve-out, and `migrate_assignment` archiving practice copies before the feasibility union is built. `purge.py` is deliberately untouched.

- [ ] **Step 5: Run them, plus the migration and retention suites**

Run: `.venv/bin/python -m pytest tests/unit/test_audit.py tests/integration/test_practice_migration.py tests/integration/test_pack_migration.py tests/integration/test_purge.py tests/guards -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add originalentry/services/audit.py originalentry/packs/migrate.py \
        tests/unit/test_audit.py tests/integration/test_practice_migration.py
git commit -m "feat: practice stays out of the trail, and a migration archives it"
```

---

## After the last task

1. Run the full suite from the repository root: `.venv/bin/python -m pytest`. About 65 minutes, against the development branch, with nothing else touching it and no source edits in flight.
2. **Then, and only with the owner's explicit consent, apply the migration to production.** It adds one `NOT NULL` boolean to `workspace` with a server default of false, so every existing workspace becomes a non-practice row. The Heroku release phase applies it on deploy.

## What this plan does not do

From the spec's non-goals, repeated so an implementer does not drift: no impersonation of a named student; no second account; no new content; no sharing of a practice copy with anyone, including admins; and no separate student-experience simulator — the copy is a real workspace, and the fidelity comes from it being the same code.
