# A teacher can work their own assignment

**Date:** 21 October 2026 · Requested after short chapter-aligned problems shipped

**Revision history.** Draft 1 was read by a builder, which found that it named the wrong gate as
the only one: `services/write.py` refuses staff writes independently of `workspace_view`, so
relaxing the decorator alone would make chapter problems writable and leave every practice-set
write refused — the "both kinds" goal failing silently on the kind that takes hours to discover.
It also found three questions only the owner could settle (migration, the audit trail, an
instructor removed from a section), now answered below, and three omissions the builder had not
been told were its to decide. Draft 2 corrects all of it.

## Intent

A teacher cannot currently do their own assignment. They can look at a student's books, but
`decorators.py:157` sets `g.read_only = is_staff` for any staff member, so every entry form,
every submit button and every reveal button is withheld. The only way for an instructor to find
out what their assignment actually feels like is to create a second account, enrol it with the
join code, and work it as a student — at which point that account appears in the progress table,
the cohort diagnostics, the mastery view and the marks CSV alongside the class.

The ask: **a teacher works their own assignment as a student would, and grades it, so they can
see what they are about to set.** A chapter of problems takes ten minutes to try; a practice set
takes hours and has far more that can go wrong. Finding out that a problem's expected entry is
unreachable, or that the feedback reads badly, is worth far more before a cohort meets it than
after.

### Why it matters more than it looks

Three things only the student view can tell an instructor, and none of them is visible from the
console:

- **Whether the feedback is any good.** The first attempt withholds which line; the second shows
  the per-line marks and the pack author's sentence about the misconception. Whether that sentence
  actually helps is a judgement only readable by being the person reading it.
- **Whether the problem is answerable.** The validator proves a problem can be *graded*. It took
  running the app to notice that the form offered four rows and a chapter could author five lines.
- **What the marks screen says.** Marks are released to a whole class at once. An instructor who
  has never seen the screen is releasing something they have not read.

### What the owner decided

Each of these was asked and answered; they are not the builder's to revisit.

1. **A private practice workspace**, opened from an action on the assignment, owned by the teacher
   and flagged as staff practice. Not a join code, not a throwaway preview.
2. **Gradable on its own.** They grade that one copy and see the marks and the evidence. The
   cohort grading run skips it.
3. **Both assignment kinds** — chapter problem sets and full practice sets.
4. **Reopening resumes**, with a separate explicit action to archive it and start fresh.
5. **Only the owning teacher can see it.** Not co-teachers, not admins.
6. **It ignores due dates and the marks-release gate**, so a mark is visible as soon as they
   grade it.
7. **A pack migration archives it**, and the teacher opens a fresh copy on the new version.
   Their throwaway work can never make a class-wide migration infeasible, and the copy can never
   quietly sit on a version no student has.
8. **Its traffic stays out of the durable audit trail.** `services/audit.py` already keeps a
   student's own workspace traffic out on purpose; practice traffic is workspace traffic.
9. **An instructor removed from the section keeps their practice copy.** Reaching it needs
   ownership, not `may_see_section`.

## Goals

- A teacher reaches a writable copy of their own assignment in one action, as themselves.
- That copy behaves exactly as a student's does: same screens, same forms, same escalating
  feedback, same reveal, same submit.
- Nothing about it reaches any class-level number or export.
- They can grade it and read the marks screen and the evidence immediately.
- They can start over without losing the ability to try again.
- It works for both kinds of pack, with no second code path for either.

## Non-goals

- **No impersonation.** Nothing here lets a teacher act *as* a named student, or see a student's
  screens as that student. The existing read-only view of a student's books is unchanged.
- **No second account.** One identity, one sign-in.
- **No new content.** A practice copy uses the assignment's own pinned pack version and nothing
  else.
- **No sharing.** Not visible to colleagues, not exportable, not linkable to anyone else.
- **No separate student-experience simulator.** The copy is a real workspace; the fidelity comes
  from it being the same code, not from a model of it.

## Anti-goals

Each of these would make the feature worse than not having it.

- **A teacher's practice work in a student-facing number.** In the progress table, the cohort
  diagnostics, the mastery rates, the marks CSV, or a `GradeRun` beside real students. This is the
  failure to design against; everything else is recoverable.
- **A teacher able to write to a student's workspace.** The read-only rule exists to stop a
  teacher altering the work they are marking. Relaxing it for a practice copy must not relax it
  anywhere else.
- **A practice copy a teacher mistakes for a student's.** If they cannot tell at a glance which
  they are looking at, the feature has created a new way to be confused about whose work is whose.
- **Losing an hour of practice to a misclick.** A practice set takes hours. "Start over" must be
  deliberate and separate from "open".
- **A second code path for the student screens.** Two implementations of the problem screen would
  drift, and the drifted one is the one the teacher sees — so what they check is not what ships.

## Constraints

- **`decorators.py:157`** is `g.read_only = is_staff or ws.archived_at is not None or ws.status
  == "submitted"`. The `is_staff` term is what has to become conditional, and only for the owner
  of a practice copy.
- **There are TWO independent write gates, and they disagree about who may write.**
  `decorators.py:157` sets `g.read_only`, which is all the chapter-problem routes consult
  (`student/views.py` `problem_submit` and `problem_reveal` call `_guard_writable`). Every
  practice-set write — entries, dispositions, posting, statements, submit — goes through
  `services.write.workspace_write`, whose `_check_gates` (`write.py:47`) independently refuses
  `actor.role != ROLE_STUDENT or actor.id != workspace.student_id`. Relaxing only the decorator
  makes problem sets work and leaves practice sets refused.
- **`_check_gates` is also where the deadline and variant rules live**, not `workspace_view`: it
  refuses on `workspace.status == "submitted"`, on `variant_id is None`
  (`messages.WAITING_FOR_VARIANT`), and on `accommodations.close_for` having passed. So "a
  practice copy ignores `due_at` and the late policy" is implemented there.
- **`workspace_view` is the only way into a `/w/` route**, proved by
  `tests/guards/test_structure.py`, and the place the problem-set fence already lives.
- **Ten modules walk an assignment's workspaces**: `services/diagnostics.py`,
  `services/mastery.py`, `services/progress.py`, `services/marks_export.py`,
  `services/grades.py`, `services/assignments.py`, `services/multicompany.py`,
  `packs/migrate.py`, `staff/views.py`, `student/views.py`. Scattering the exclusion across them
  is how one gets missed.
- **`uq_workspace_assignment_student_live`** is a unique index on `(assignment_id, student_id)`
  where `archived_at IS NULL`. A practice copy occupies the teacher's own slot in it, so one live
  practice copy per teacher per assignment comes free, and `archive_and_restart` is the reset
  path that already respects it.
- **`Workspace.student_id`** is the column a practice copy's owner goes in. The name is about
  student work, not about roles; it is a foreign key to `user.id`.
- **`student/views.py:1257`** gates the marks screen on `assignment.marks_released_at`.
- **`open_workspace`** refuses when `prerequisite_met` is false and when the assignment is
  student-choice (`fixed_pack_version_id is None`).
- **`grade_section(session, assignment, actor, limit, after_id)`** grades in id order and stores
  a `GradeRun` per workspace.
- **More reads a practice copy to be kept out of than the obvious five.** Beyond
  `cohort_diagnostics`, `assignment_mastery`, `assignment_progress`, `marks_csv` and
  `grade_section`: `services/assignments.py:311` (`variant_for` counts live workspaces for
  round-robin, so a practice copy shifts which variant the *next student* is handed — a
  correctness bug, not a cosmetic one), `staff/views.py:269` (grading roster), `:246`
  (archived-books list), `:173` (assignment list's workspace count), `:150` (dashboard total),
  `:855` (catalogue's per-pack-version usage) and `:1097` (student directory's status counts).
- **`services/purge.py` must NOT exclude practice copies.** Retention deletion has to reach every
  row or it orphans records behind foreign keys. The chokepoint is for reads and reports; purge
  is neither.
- **`services/audit.py:should_audit`** returns True for any signed-in staff user, with no
  blueprint filter beyond `SKIP_ENDPOINTS`. Its docstring states why a student's own workspace
  traffic is deliberately excluded: logging it durably "would make a purgeable, PII-light record
  durable and identifying, which the retention split forbids."
- **`staff/views.py:226` `_workspace_or_404`** scopes by assignment and section only, and feeds
  `grading_detail`, `workspace_archive`, `workspace_reopen`, `grading_override`,
  `grading_comment` and `progress_variant`. Owner-only is not enforceable at `workspace_view`
  alone.
- **`abort(404)`, never 403**, for a workspace the caller may not see.
- Amounts are cents. The CSP forbids inline styles. Tailwind emits nothing for an unscanned
  utility, silently. `ruff check originalentry tests` must stay clean — 6 pre-existing findings
  in untouched files as of `ad4eedc`.
- The suite runs against the Neon development branch when `TEST_DATABASE_URL` is set. Two
  concurrent runs deadlock. Migration head is `b5f08c2a91d6`.

## Design

### One flag, one chokepoint, one guard

`Workspace` gains a boolean marking a staff practice copy. Everything else follows from where
that flag is read.

**The exclusion is not a condition each caller remembers.** It is a single helper — one function
that returns an assignment's class-facing workspaces — and every class-level query goes through
it. A guard test walks the source of the ten modules above and fails if any of them queries
`Workspace.assignment_id` without it, in the idiom of
`tests/guards/test_scoping.py::test_every_scoped_console_route_goes_through_one_of_the_two_lookups`.

This is a deliberate repeat of what made the problem-set fence trustworthy: the fence is one
check inside `workspace_view` with a guard that keeps the classification deliberate, and it held
under review while several scattered things did not. The cost of a miss is different in kind here
— not a confusing screen but a teacher's practice marks in a gradebook, which an instructor would
have no reason to disbelieve.

**The rule has one definition and two callers.** The flag is not read in two places that could
disagree: a single predicate answers "may this actor write to this workspace", and both
`workspace_view` (to set `g.read_only`) and `write.py:_check_gates` (to admit or refuse) call it.
That keeps the chokepoint argument honest — one definition of the rule — without threading a
computed boolean through `workspace_write`'s signature at every call site. A guard test asserts
that neither gate decides it independently.

**Why a boolean and not a role check.** A teacher is a `user` with an instructor role, but role
is mutable and a workspace is not: an account that stops being staff must not retroactively turn
a practice copy into a student's record, and an account promoted to staff must not turn their old
student work into practice. The flag records what the workspace *is*, decided when it was opened.

### Writable, for exactly one person

`workspace_view` already loads the workspace, the pack and the caller. The read-only decision
becomes: staff see a workspace read-only **unless** it is a practice copy and they own it. Every
other combination is unchanged — a teacher viewing a student's books, an admin viewing anything,
an archived or submitted workspace.

Visibility follows the same rule and is stricter than the existing one: a practice copy is
reachable by its owner alone. The admin override that reaches every student workspace does not
reach it, and neither does a co-teacher of the section. A caller who is not the owner gets 404,
like every other refusal.

### Opening, resuming, starting over

An action on the assignment opens a practice copy, pinned to the assignment's own
`fixed_pack_version_id` with a variant handed out by the assignment's own policy. Opening it
again returns the same copy. A separate, explicitly-labelled action archives it and opens a fresh
one, through `archive_and_restart`.

A practice copy ignores what a student's cannot: the prerequisite chain, `opens_at`, `due_at`,
the late policy, and `marks_released_at`. A teacher preparing next term's assignment must be able
to work it before it opens, and the marks screen is the one screen they most need to read before
releasing marks to a class.

Two assignment shapes have no single answer to "which pack version, which variant", and both are
the builder's call; refusing with an explanation on screen is acceptable for a first version in
each case, and silently producing an unusable copy is not.

- **A student-choice assignment** has no pinned version at all (`fixed_pack_version_id is None`).
- **A manual-variant assignment** hands out no variant: `variant_for` returns None for
  `variant_policy == MANUAL`, and `_check_gates` then refuses every write with
  `WAITING_FOR_VARIANT`. The only hand-out UI is `staff.progress_variant` on the progress screen,
  which the chokepoint excludes practice copies from — so a practice copy on such an assignment
  would be unwritable with nothing on screen to fix it.

**An account that was a student first.** `open_workspace` returns any existing live workspace
unchanged, so a student later promoted to instructor would be handed their own old, unflagged
student workspace as "their practice copy" — read-only, no banner, and
`uq_workspace_assignment_student_live` blocks opening a real one beside it. The open action
refuses in that case and says why, rather than converting work that was done as a student.

### Telling it apart, on every page

A practice copy carries a standing banner on every screen of it, in the slot the read-only notice
already uses — saying that this is the teacher's own copy and is not part of the class data. This
is what keeps the "mistakes a practice copy for a student's" anti-goal from being live: the
teacher is the only person who can see it, and they are told what it is every time they look.

The console says so too. Wherever a teacher can open or resume one, the action distinguishes
"work this myself" from "start over", and an assignment with a live practice copy says so rather
than silently resuming.

### Which staff actions a practice copy accepts

Owner-only has to be enforced at `_workspace_or_404` as well, or a co-teacher or admin holding the
public id reads and writes a colleague's practice copy through the six routes it feeds. Which of
those actions a practice copy accepts *from its owner* is per-route and the builder's call, with
one constraint: an action whose purpose is one person marking another's work has no meaning on a
copy where both are the same person, and offering it is worse than refusing it.

### Migration archives it

`packs/migrate.py` walks an assignment's workspaces for the feasibility union — `missing_accounts`,
`missing_parties`, `missing_documents`, `missing_variants`, `changed_identity`. A practice copy is
**archived** by the migration rather than included or left behind: included, a teacher's throwaway
entry referencing an account the new version drops could make a whole section's migration
infeasible; left behind, the copy sits on a version no student has. Archived, the teacher opens a
fresh copy on the new version and nothing about their practice can block the class.

This makes migrate the one write path the chokepoint touches, and it needs its own name — a report
helper that silently excluded practice copies here would leave them pinned to a dead version.

### The audit trail does not record it

`should_audit` returns True for any staff request, so a teacher working a practice set for hours
would write one never-purged `AuditLog` row per request, all labelled `student.*`, visible to
admins in `staff.activity` and its CSV export. That contradicts two things at once: the owner-only
decision, and `audit.py`'s own stated reason for keeping a student's workspace traffic out of the
durable trail.

Practice traffic is workspace traffic. `should_audit` gains the carve-out — the first per-workspace
condition in a function written as a pure, shared decision, so it needs a test of its own saying
why. The purgeable `activity_event` record is unaffected and still carries what the teacher did.

### Grading one copy

A per-workspace grading action grades the practice copy and stores its `GradeRun` as any other
workspace's. `grade_section` skips practice copies via the chokepoint, so a cohort run never
produces one. The marks screen and the evidence then read exactly as a student's would after
release.

Whether a practice copy's `GradeRun` rows need distinguishing from a student's in the grading
history is the builder's call. Nothing reads them by assignment without going through the
chokepoint, so the simple answer — store them identically — is defensible.

### What this does not touch

The student screens, the grading engine, the rubric components, the packs, the fence between
problem sets and practice sets, and the read-only view of a student's books. A practice copy is a
`Workspace` row with a flag; the fidelity of the feature comes from changing as little as
possible.

## Known limitations

- **A teacher can see the answer key anyway.** `staff.answer_key_print` is staff-only and shows
  the expected entries, so a teacher working their own assignment can look up the answers. That
  is not a leak — it is their key — but it means a practice copy's *mark* measures nothing. Its
  value is the experience, not the score.
- **One practice copy per assignment at a time.** The unique index allows one live workspace per
  (assignment, user). A teacher cannot keep two in progress to compare variants.
- **Practice copies accumulate as archived rows.** Starting over archives rather than deletes, in
  keeping with how student work is handled. Nothing prunes them.
- **A co-teacher cannot see a colleague's practice run**, which is the decision, but it means two
  instructors preparing one course cannot compare notes inside the app.
- **The exclusion is only as good as the guard.** A new module that walks workspaces without the
  chokepoint is a hole; the guard is what makes that a failing test rather than a discovery.
- **A practice copy does not survive a pack migration.** It is archived, so a teacher mid-way
  through practising an assignment that gets migrated loses that run and starts again.
- **Admins cannot audit what a teacher did in a practice copy.** That is the decision, and it
  means the durable trail no longer accounts for every staff request. The purgeable
  `activity_event` record still carries it.

## Left to the builder

- The flag's name and whether it is a boolean or a nullable timestamp recording when the copy was
  opened; the repo uses nullable timestamps for several workspace lifecycle facts.
- The chokepoint's name, signature and module, and whether it returns workspaces or a query.
- Exactly where the actions live in the console — the assignment list, the progress screen, or
  both — and their wording.
- Whether a student-choice assignment refuses a practice copy or offers the company picker.
- Whether a practice copy's `GradeRun` rows are distinguished in storage.
- Whether the banner reuses `g.read_only_message` or gets its own slot.
- How the guard recognises a compliant query — imported-name inspection, as
  `test_import_boundaries.py` does, or source inspection, as `test_scoping.py` does.
- Which of the six `_workspace_or_404` routes a practice copy accepts from its owner.
- Whether a student-choice assignment and a manual-variant assignment refuse a practice copy or
  offer a picker, and the wording of the refusal.
- Whether the round-robin count, the dashboard total, the catalogue usage figure and the student
  directory's status counts exclude practice copies or are audited exemptions — the round-robin
  one is a correctness bug either way and must exclude.
