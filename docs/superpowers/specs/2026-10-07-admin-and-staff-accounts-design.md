# Scoped visibility, admin accounts, and adding teachers in the app

**Date:** 7 October 2026 · revised the same day, when scoping changed the shape of it

## Intent

**Every teacher can currently read every student's marks in the system.** There is no concept of
whose section a section is — not on `Section`, not on `Assignment`, nowhere in the data model — so
the console shows all of it to anyone with a staff role.

This fixes that, and does the two things needed to make the fix coherent: an admin role to be the
exemption, and a screen for managing staff so sections can be handed to the right teacher.

### What the owner asked for

> there needs to be an admin account and there needs to be a method, in app, for adding teacher
> users

then, which reframed it:

> teachers shouldnt be able to see everyones marks, only their own

The second is the substance. The admin role is close to pointless without it: if every teacher
already sees everything, "admin" gates a few buttons and means nothing. What makes admin *mean*
something is being the role that sees everything **when teachers do not**.

## What is true now

| | |
| --- | --- |
| Section ownership | **None.** No owner on `Section` or `Assignment`; nothing records who teaches what |
| Roles | `student`, `grader`, `instructor` — a `String(16)` column, default `student` |
| Who counts as staff | `STAFF_ROLES = {grader, instructor}`, defined in **both** `decorators.py:25` and `auth/views.py:47` |
| `grader` vs `instructor` | **No difference.** Nothing in the app branches on which one you are |
| `ROLES` | Exported, and **nothing reads it**. `cli.py` hand-writes its own role list |
| Making a staff account | `flask staff add <email> --role instructor\|grader`. No audit record, no email sent |
| Removing one | Nothing. `flask auth revoke` ends their sessions; they sign straight back in |
| `is_active` | Hardcoded `return True` on `User` |
| Staff route guard | `staff_view` → `abort(404)`, not 403, so a refusal does not confirm the page exists |
| Staff console size | 26 endpoints, 16 of them already behind one lookup helper |

## Decisions

- **Ownership** is a `(section, staff)` join table, so a section can have two teachers and a TA.
- **Existing sections** are attached to the first admin by the migration, then reassigned in the app.
- **Admin powers:** manage people and section staffing, plus uploading a company pack. See the
  correction below.
- **Adding a teacher** sends them a sign-in code immediately, reusing the email the app already sends.
- **Removing a teacher** deactivates the account: sign-in blocked, record kept.
- **Roles offered** are Teacher and Admin. `grader` is no longer offered.

### Correction: only one of the four "dangerous" operations should be admin-only

An earlier pass gated four irreversible operations to admins — pack upload, releasing marks,
archiving a book, rotating a join code. **Scoping changes that calculus, and three of them should
go back to teachers.**

The reason those four looked dangerous was that an unscoped teacher could fire them against
*anyone's* section. Once a teacher only reaches their own sections:

| Operation | With scoping | Who |
| --- | --- | --- |
| `catalogue_upload` | Still cohort-wide: every section that later pins that version gets it | **Admin** |
| `grading_release` | Releases their own section's marks | Teacher — it is the job |
| `workspace_archive` | Archives their own student's book | Teacher |
| `section_rotate_code` | Rotates their own section's code | Teacher |

A teacher who cannot release the marks they just graded cannot teach the course. The premise of
that earlier decision was the leak this spec exists to close.

### Why "admin-only" cannot extend to the CLI

A CLI command cannot be role-gated: outside a request there is no `current_user`, so shell access
*is* the permission. `packs import`, `packs migrate`, `grade assignment` and `auth revoke` stay
terminal jobs — and a migration that rewrites live student marks is better done deliberately from
a terminal than from a web form. Gating them would mean *building* screens for them, which is its
own project.

## Section 1: the role and permission model

**`ROLE_ADMIN = "admin"`**, a fourth role. It fits the existing `String(16)` column, so the role
itself needs **no migration** and existing rows are untouched.

`ROLES` gains it too, but be clear about what that does: **`ROLES` is exported and nothing reads
it.** Nothing validates a role against it — `cli.py` hand-writes `click.Choice([ROLE_INSTRUCTOR,
ROLE_GRADER])` instead. So adding admin to `ROLES` keeps the declared set honest and nothing more,
and forgetting it would break no test. The better move while in there is to make the CLI's choice
derive from the one declaration rather than repeat it — the same mistake as the duplicated
`STAFF_ROLES`, in a smaller form.

**Admins are staff.** `STAFF_ROLES` becomes `{grader, instructor, admin}`, so every route a
teacher reaches an admin reaches too. Admin is additive.

**One owner for the role sets.** `decorators.py` keeps `STAFF_ROLES` and gains
`ADMIN_ROLES = {admin}`; `auth/views.py` deletes its copy and imports instead. No cycle:
`decorators` imports from `models`, and nothing imports `auth`.

> This is the part worth doing even if nothing else ships. Two definitions of who counts as staff
> is a latent security bug, not untidiness — and duplication of exactly this kind has already
> caused a defect in this codebase.

**`admin_view`** mirrors `staff_view`, including `abort(404)` rather than 403, for the reason
`staff_view` already gives: a refusal that confirms the page exists tells a prober something.

**Templates check the role as well as the routes.** An Upload button rendered to a teacher who
then meets a 404 is secure and baffling. The route guard is the security boundary; the template
check is so nobody reaches it by accident.

**Bootstrap is the CLI, and that is correct.** `flask staff add <email> --role admin` extends the
existing `--role` choice. The first admin cannot come from inside the app; something has to break
the circle, and shell access is the right thing to require.

**Audit.** `staff_actions` gains `STAFF_INVITED`, `STAFF_ROLE_CHANGED`, `STAFF_DEACTIVATED`,
`STAFF_REACTIVATED`, `SECTION_STAFF_ADDED`, `SECTION_STAFF_REMOVED`. The CLI writes no audit
record today, so moving this in-app gains traceability rather than spending it.

### Tests

- A teacher gets 404 on `catalogue_upload`; an admin does not.
- An admin reaches every staff route.
- One test asserts the role sets have collapsed to a single definition, so the duplication cannot
  quietly return.

## Section 2: who sees whose marks

The substance. **`SectionStaff`**, mirroring `Enrollment` exactly — composite primary key on
`(section_id, user_id)` — plus `added_at` and `added_by_id`, so the audit answers who granted
access. One teacher is one row; a co-taught section is two. No per-section role: giving `grader`
real limits was declined, and this is where such a column would go if that changes.

**Enforcement is three chokepoints and three queries.**

| Where | Covers |
| --- | --- |
| `_assignment_or_404` gains the check | 16 routes, including every grading and marks route |
| New `_section_or_404`, replacing four identical inline `db.session.get(Section, …)` lookups at lines 570, 587, 609 and 648 | 4 section routes |
| `index`'s assignment query joins `section_staff` | the dashboard |
| `assignment_new` and `assignment_create` section lists | the form |
| `catalogue`, `answer_key_print` | unowned by design — a company pack is nobody's, and a printed answer key is teaching material, not student data |

`_workspace_or_404(assignment, public_id)` already filters by `assignment_id`, so every per-student
route is nested under the assignment chokepoint and needs no check of its own.

### The trap worth naming

`assignment_create` reads its section from the posted form at line 506. **Filtering the dropdown is
not a permission check** — a crafted POST would otherwise create an assignment inside a
colleague's section. The posted id is verified, not merely the rendered options. The same applies
to any other route that takes an id from a form rather than the path.

**Admins are exempt**, through one helper the three chokepoints share. That exemption is what
finally makes the role mean something.

**Backfill:** the migration attaches every existing section to the first admin account, so nothing
breaks on deploy and no teacher's dashboard empties. Sections are reassigned from the screen
afterwards.

**Attaching staff is admin-only** to start. Whether a teacher may add a co-teacher to their own
section is a real question, deliberately left closed until the feature has been used.

### The test that makes this safe rather than hopeful

Every missed query is a data leak, and there are 26 endpoints. So instead of 26 hand-written tests,
**one parameterised test walks `app.url_map` for `/staff/` rules and asserts each refuses a teacher
who does not teach that section.** The unowned endpoints sit in an explicit allowlist, named one by
one, so excluding one is a decision somebody wrote down.

The point is next year: a new staff route is covered the moment it is added, or the test fails and
makes somebody decide. A hand-written suite silently omits the route nobody remembered.

Plus the ordinary cases:

- An admin reaches everything.
- A teacher reaches their own sections and no others.
- A co-teacher on the same section sees the same marks.
- `grading_marks_csv` and `diagnostics_export` are both scoped — the two routes that hand student
  data out in bulk.
- A crafted `assignment_create` POST naming another teacher's section is refused.

## Section 3: the people screen

**`GET /staff/people`**, admin only: one row per staff account — name, address, role, last sign-in,
active or not, and which sections they teach. Existing `grader` accounts display as **Teacher** with
their stored role noted; nobody's row is rewritten.

**`POST /staff/people`** takes an address, optional names, and Teacher or Admin.

| The address | What happens |
| --- | --- |
| Has no account | Create it with that role, and invite them |
| Has a **student** account | **Refused**, naming the conflict and suggesting a separate staff address |
| Has a staff account already | Say so; do not re-invite. Changing a role is a different action |

The student case is deliberate. One address being both a student with marks and a teacher who can
read a whole section's marks is an integrity problem, not an inconvenience. A teaching assistant is
the person who will hit this, so the wording has to explain rather than merely refuse.

**The invite reuses the existing sign-in email.** `issue_token(..., ip=None)` then
`send_sign_in_email`: the teacher gets a link and a code and is in within a minute. No new
template, no new token type.

`ip=None` is deliberate. The per-IP ceiling is 30 an hour and would throttle an admin adding a
department from one desk; the guard is `if ip_hash:`, so passing none skips exactly the limit that
should not apply while keeping the per-address limits that protect the recipient. This is the
reasoning `issue_staff_code` was written for — "because staff, not the address, asked for it".

> **Known limitation.** That token lives 15 minutes, so a teacher invited at 5pm finds a dead link
> next morning. It matters little, because their account exists and the ordinary "email me a code"
> flow works — but the email says *sign in*, not *you have been given access*, since it is the
> existing copy. A dedicated invite email with a multi-day token is a small follow-on, not part of
> this.

**`POST /staff/people/<public_id>/role`** switches Teacher ↔ Admin, with two invariants enforced in
the route:

- An admin cannot change their own role — the obvious way to lock yourself out.
- The last admin cannot be demoted, checked in the same transaction so two admins demoting each
  other concurrently cannot both succeed.

**`POST /staff/people/<public_id>/sections`** attaches and detaches sections. This is how a teacher
gets the class they teach, and it is the screen that makes the backfill correctable.

**`issue_staff_code` stays dead.** Wiring it here was considered and rejected: its 30-minute,
no-link code is worse for onboarding than a link. It should be deleted or wired elsewhere, as its
own decision.

### Tests

- Inviting an unknown address creates the account and sends one email.
- Inviting a student's address is refused and creates nothing.
- Inviting an existing staff address does not issue a second token.
- An invite is not subject to the per-IP limit; it is still subject to the per-address limit.
- An admin cannot change their own role; the last admin cannot be demoted.
- Attaching a section makes it appear on that teacher's dashboard; detaching removes it.
- A teacher cannot reach the people screen at all.

## Section 4: deactivation

The only other schema change: **`deactivated_at: datetime | None`** on `User`. Nullable, no
backfill.

**`is_active` stops lying** — `return self.deactivated_at is None` in place of `return True`.

**Live sessions die on the next request.** The session loader in `app.py` (which resolves
`public_id:session_epoch`) also returns `None` for a deactivated account. One chokepoint covers both
existing sessions and new ones, which is why it belongs there rather than in a decorator.
Deactivating also bumps `session_epoch`, the mechanism already built for signing someone out of
every device.

**A deactivated person who types a valid code is told the truth:** *"That account is no longer
active. Ask your administrator."* `consume_code` will match, because the code is real, so the
verify view checks after the match.

> **Why this does not contradict E1.** E1 governs the *request* step, where an unauthenticated
> stranger must not learn whether an address has an account. Someone holding a valid code has
> proved they receive that mailbox, so naming the state tells them nothing they should not know.
> For the same reason **the request step gets no special case at all** — a deactivated address
> appears to be sent a code exactly like any other. E1 stays intact.
>
> This is the same judgement as the unmerged `code-miss-message` branch, which distinguishes an
> already-used code from an expired one once possession is proven. The two should land together.

**Nothing is deleted.** Their name stays on every override, comment and audit row — that is the
entire reason for deactivating rather than removing. Their `SectionStaff` rows go, so their
sections become unstaffed and visible to admins until reassigned.

**Reactivation** clears the stamp and does not restore sessions; they sign in again. It does not
restore their sections either — that is deliberate, because reinstating someone's access to a
class is a decision, not a side effect.

**Two invariants**, as for the role change: you cannot deactivate yourself, and you cannot
deactivate the last active admin, both checked in the transaction.

**Scope line:** the column is on `User`, so the mechanism is general, but the screen manages staff
only. Deactivating students stays out — they are governed by rosters and sections, a different
question.

### Tests

- A valid code from a deactivated account is refused with that message.
- A live session dies on the next request after deactivation.
- The audit trail, overrides and comments survive deactivation.
- Their sections become unstaffed, not reassigned.
- Self-deactivation and last-admin deactivation are both refused.
- Reactivation requires a fresh sign-in and restores no sections.
- The request step behaves identically for active, deactivated and unknown addresses — the E1
  guarantee, tested directly.

## Build order

The sections are in dependency order and should be built that way:

1. **The permission model**, because the scoping exemption needs `ADMIN_ROLES` to exist.
2. **Scoping**, because it is the fix and everything else is scaffolding around it.
3. **The people screen**, because it is how the backfill gets corrected.
4. **Deactivation**, which is independent and could ship separately.

Shipping 1 and 2 without 3 is viable but uncomfortable: every section belongs to the first admin
and only the CLI can change that.

## Out of scope

- **Gating the CLI.** It cannot be role-gated; see above.
- **Pack operations in the app** (import, diff, migrate as admin screens). Its own spec.
- **Giving `grader` real limits.** Declined: it would mean a permission decision on every staff
  route, which is most of the work and none of the ask.
- **A teacher adding their own co-teacher.**
- **Deactivating students.**
- **A dedicated invite email** with a multi-day token.
- **Scoping the student-facing side.** Students already see only their own work.

## Risks

- **A missed query is a data leak**, and that is the whole risk of this spec. The `url_map`-driven
  test is the mitigation, and its allowlist is the thing to review most carefully: every name on it
  is a route somebody decided not to scope.
- **Reporting across sections stops working.** A head of department who wants cohort-wide
  diagnostics now needs an admin account. That is correct but it is a change in what the
  diagnostics screen means, and worth saying to whoever uses it.
- **The backfill concentrates everything on one account.** Between deploy and reassignment, one
  person holds every section. Short window, but do it in a quiet hour.
- **Locking out the only admin.** The two invariants guard against it, but a single admin who loses
  their mailbox still needs `flask staff add` to recover. That break-glass path should stay
  documented, not removed.
- **The 15-minute invite link** will read as broken to a teacher who opens it the next day. The
  flash message should say the link is short-lived and that signing in works regardless.
- **A teaching assistant with one address.** The student-account refusal is correct but will be met
  by real people; if it becomes common, the answer is a decision about whether one person may hold
  two roles, not a loosening of the check.
- **`release_marks` still has no guard** against releasing half-graded work. Scoping limits the
  blast radius to one section but does not close it. Worth fixing, separately.
