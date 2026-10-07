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
| Routes that touch student data | **55** — 26 under `/staff/`, 29 under `/w/`, all 29 of the latter behind `workspace_view` |

## Decisions

- **Ownership** is a `(section, staff)` join table, so a section can have two teachers and a TA.
- **Existing sections** are attached to every current staff account by the migration, so deploy day
  changes nothing, and pruned afterwards on the people screen. Deploying does not close the leak;
  pruning does.
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

### What admin means, said plainly

An admin can read **every student's books and every student's marks, across every section**. There
is no per-section grant for admins and no audit of admin reads. So the honest answer to "who can
see my work" becomes: the teachers of my section, and anyone holding the admin role.

That is stated here rather than left as an inference from a decorator, because it is the privacy
posture of the whole tool and it is the sentence that should make somebody ask whether admin ought
to be two roles — one that manages accounts and one that reads everything. This spec says no, on
the grounds that a department tool with a handful of staff does not need that separation yet. If
the tool ever serves more than one department, revisit it first.

### All 55 routes, and what happens to each

The previous pass of this spec asserted "three chokepoints and three queries" and was wrong by 29
routes, because counting chokepoints is what let `workspace_view` go unnoticed. So here is the
enumeration instead, generated from `app.url_map`. A reviewer can audit this; they cannot audit a
sum.

**Scoped by `workspace_view` (29).** Every `/w/` route. `is_staff` becomes "staff who teach this
workspace's section, or admin", reached by `Workspace.assignment_id` → `Assignment.section_id` →
`section_staff`:

`student.checkpoints` · `checkpoint_submit` · `disposition` · `document` · `document_image` ·
`documents` · `entry_create` · `entry_new` · `entry_void` · `general_ledger` · `how_to` ·
`journal` · `journals` · `marks` · `overview` · `post_entry_sub` · `post_general` ·
`post_subsidiary_all` · `posting_reverse` · `print_record` · `reference` · `reference_index` ·
`statement` · `statement_save` · `statements` · `submit` · `submit_confirm` · `subsidiary` ·
`trial_balance`

**Scoped by `_assignment_or_404` (16).** Every staff route that names an assignment:

`staff.assignment_checkpoints` · `assignment_clone` · `diagnostics` · `diagnostics_export` ·
`grading` · `grading_comment` · `grading_detail` · `grading_marks_csv` · `grading_override` ·
`grading_release` · `grading_run` · `progress` · `progress_accommodation` · `progress_variant` ·
`workspace_archive` · `workspace_reopen`

**Scoped by a new `_section_or_404` (4),** replacing four identical inline
`db.session.get(Section, section_id)` lookups at lines 570, 587, 609 and 648:

`staff.section_availability` · `section_availability_set` · `section_roster_import` ·
`section_rotate_code`

**Scoped by their own query (3).** No id in the path, so there is nothing for a chokepoint to
check:

| Route | What changes |
| --- | --- |
| `staff.index` | the assignment list joins `section_staff` |
| `staff.assignment_new` | the section dropdown lists only sections you teach |
| `staff.assignment_create` | **verifies the posted `section_id`**, not merely the rendered options |

**Unowned, by decision (3).**

| Route | Why |
| --- | --- |
| `staff.catalogue` | A company pack belongs to nobody; seeing what is loaded is not student data |
| `staff.catalogue_upload` | Same, but cohort-wide, so **admin-only** |
| `staff.answer_key_print` | A printed answer key is teaching material, not student data |

29 + 16 + 4 + 3 + 3 = 55.

### The trap worth naming

`assignment_create` reads its section from the posted form at line 506. **Filtering the dropdown is
not a permission check** — a crafted POST would otherwise create an assignment inside a
colleague's section. The posted id is verified, not merely the rendered options.

### One helper, and a switch to turn it off

Every chokepoint calls the same function:

```python
def may_see_section(section_id: int) -> bool:
    """Whether the signed-in staff member may see this section's students.

    One function, because a scoping rule implemented in four places is a scoping rule with four
    chances to differ. The flag is here and nowhere else for the same reason: a half-disabled
    guard is worse than either state.
    """
    if not current_app.config["SCOPED_VISIBILITY"]:
        return True
    if current_user.role in ADMIN_ROLES:
        return True
    return db.session.execute(
        db.select(SectionStaff.user_id).filter_by(
            section_id=section_id, user_id=current_user.id)
    ).first() is not None
```

**`SCOPED_VISIBILITY` defaults to `True`** and exists because this change can lock every teacher
out of every class at once, and it would be deployed mid-term. Without it, a scoping misfire on
deploy morning is fixed by a code deploy under pressure; with it, it is fixed by
`heroku config:set SCOPED_VISIBILITY=0` while somebody reads the logs. Ten lines of insurance
against a bad morning.

It is checked in this one function, never inline at a call site, so the flag cannot leave half the
routes scoped and half not.

### Backfill: every existing section to every current staff member

The migration attaches every section to **every account that currently holds a staff role**.

An earlier pass said "the first admin account", which does not exist when the migration runs —
the admin role is new in the same change, so there is nobody to attach to. This version has no
such hole, and it has a property worth having: **day one is behaviourally identical to today.**
Every teacher still sees everything, nothing breaks on deploy, and nobody is locked out of a class
mid-term by a migration.

> **So deploying this does not fix the leak.** It ships the mechanism. The leak closes when an
> admin prunes the attachments on the people screen, and the spec says so plainly rather than
> letting a green deploy read as a solved problem. If there is only one staff account today, the
> backfill is already correct and there is nothing to prune.

The people screen shows a count — *"54 sections are attached to 3 teachers"* — so the outstanding
work is visible rather than remembered.

### The test that makes this safe rather than hopeful

Every missed route is a data leak, and there are 55. So instead of 55 hand-written tests, **one
parameterised test walks `app.url_map` and asserts each `/staff/` and `/w/` route refuses a teacher
who does not teach that section.**

This extends a convention the repository already has: `tests/guards/test_structure.py:20-41` walks
the URL map for both prefixes, asserting every `/w/` route carries `@workspace_view` and every
`/staff/` route carries `@staff_view`. The new test belongs beside those and asks the next question
— not *is it guarded* but *is it scoped*.

Two facts make it far smaller than it looks, and the previous pass of this spec specified neither:

1. **The guards abort before the view body runs.** `workspace_view` refuses inside the decorator;
   each staff view calls `_assignment_or_404` or `_section_or_404` on its first line. So the inner
   path parameters — `key`, `ref`, `entry_id`, `statement_type`, `kind`, `section`, `run_id` — are
   never examined on the refusal path and **placeholders are sufficient**. Only three ids must be
   real.
2. **`tests/conftest.py:77` already sets `WTF_CSRF_ENABLED=False`**, so the 25 POST routes need no
   token.

```python
# tests/guards/test_scoping.py
FOREIGN = {}          # filled by the fixture: a section, assignment and workspace owned by someone else
PLACEHOLDERS = {"key": "sales", "ref": "D01", "entry_id": "1", "statement_type": "trial_balance",
                "kind": "customer", "section": "chart", "run_id": "1",
                "pack_version_id": "1", "variant_code": "A"}

# Every name here is a route somebody decided not to scope. Review this list, not the count.
UNOWNED = {"staff.catalogue", "staff.catalogue_upload", "staff.answer_key_print",
           "staff.people", "staff.people_add", "staff.people_role", "staff.people_sections"}


def _scoped_rules(app):
    for rule in app.url_map.iter_rules():
        if not (rule.rule.startswith("/staff") or rule.rule.startswith("/w/")):
            continue
        if rule.endpoint in UNOWNED:
            continue
        yield rule


def test_every_scoped_route_refuses_a_teacher_from_another_section(client, foreign, teacher):
    """A teacher who does not teach this section gets 404 on every route that touches it.

    Driven off the URL map rather than a list, so a route added next year is covered the moment it
    exists -- or this fails and makes somebody decide. A hand-written suite omits the route nobody
    remembered, which is how the first draft of this spec missed twenty-nine of them.
    """
    sign_in(client, teacher)
    leaked = []
    for rule in _scoped_rules(client.application):
        args = {**PLACEHOLDERS, **{k: foreign[k] for k in rule.arguments if k in foreign}}
        url = url_for(rule.endpoint, **{k: args[k] for k in rule.arguments})
        for method in sorted(rule.methods & {"GET", "POST"}):
            response = client.open(url, method=method)
            if response.status_code != 404:
                leaked.append(f"{method} {rule.endpoint} -> {response.status_code}")
    assert not leaked, "routes that did not refuse a foreign teacher:\n  " + "\n  ".join(leaked)
```

Plus the ordinary cases, which matter as much because scoping that over-refuses has broken marking
rather than secured it:

- An admin reaches everything.
- A teacher reaches their own sections and no others.
- A co-teacher on the same section sees the same marks.
- **A teacher can still open their own student's books** at `/w/`, and still sees the banner naming
  whose books they are — `workspace_view` deliberately opens archived books to staff (I2.4), and
  that has to keep working.
- `grading_marks_csv` and `diagnostics_export` are both scoped — the two routes that hand student
  data out in bulk.
- A crafted `assignment_create` POST naming another teacher's section is refused.
- With `SCOPED_VISIBILITY=0`, every one of the above opens again — the switch is tested, not
  assumed.

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

### Nothing is deleted, including their sections

Their name stays on every override, comment and audit row. **And their `SectionStaff` rows stay
too.**

An earlier pass of this spec said the rows "go", one sentence after asserting that nothing is
deleted. Both the contradiction and the deletion were wrong: those rows are the only record of who
taught a class, which is exactly what an audit trail is for. *"Who was teaching ACCT1010 last
spring?"* is a question a department will ask, and a `DELETE` on offboarding is how it becomes
unanswerable.

The behaviour that deletion was reaching for — reactivation should not silently hand someone a
class back — is a policy, not a schema operation. `may_see_section` already refuses a deactivated
user, because they cannot hold a session at all. So:

- Deactivating **keeps** the rows. The sections keep their teacher of record and remain visible to
  admins and to any co-teacher.
- A section whose only teacher is deactivated shows on the people screen as needing a teacher.
  Nobody is silently locked out of a class, and nobody has to remember which ones.
- **Reactivation restores their sections**, because the rows were never removed. If that is wrong
  for a particular person, an admin detaches the sections — a visible action with an audit row,
  rather than a side effect of a timestamp.

**Two invariants**, as for the role change: you cannot deactivate yourself, and you cannot
deactivate the last active admin, both checked in the transaction.

**Scope line:** the column is on `User`, so the mechanism is general, but the screen manages staff
only. Deactivating students stays out — they are governed by rosters and sections, a different
question.

### Tests

- A valid code from a deactivated account is refused with that message.
- A live session dies on the next request after deactivation.
- The audit trail, overrides and comments survive deactivation.
- **Their `SectionStaff` rows survive**, and the section reports that it needs a teacher.
- Reactivation requires a fresh sign-in and restores the sections they held.
- Self-deactivation and last-admin deactivation are both refused.
- The request step behaves identically for active, deactivated and unknown addresses — the E1
  guarantee, tested directly.

## Build order

The sections are in dependency order and should be built that way:

1. **The permission model**, because the scoping exemption needs `ADMIN_ROLES` to exist.
2. **Scoping**, because it is the fix and everything else is scaffolding around it.
3. **The people screen**, because it is how the backfill gets corrected.
4. **Deactivation**, which is independent and could ship separately.

Shipping 1 and 2 without 3 is viable and, with the backfill as specified, harmless — every teacher
still sees what they see today, because nothing has been pruned yet. But the leak stays open until
3 ships and somebody uses it, so 1 and 2 alone are a mechanism rather than a fix.

`SCOPED_VISIBILITY` makes the sequencing safe in the other direction too: 1 and 2 can ship with the
flag off, be exercised against production data by an admin flipping it for themselves, and be turned
on for everyone once the pruning is done.

## Out of scope

- **Gating the CLI.** It cannot be role-gated; see above.
- **Pack operations in the app** (import, diff, migrate as admin screens). Its own spec.
- **Giving `grader` real limits.** Declined: it would mean a permission decision on every staff
  route, which is most of the work and none of the ask.
- **Splitting admin into two roles** — one that manages accounts, one that reads everything.
  Declined for a departmental tool with a handful of staff; the first thing to revisit if that
  stops being true.
- **Auditing admin reads.**
- **A teacher adding their own co-teacher.**
- **Deactivating students.**
- **A dedicated invite email** with a multi-day token.
- **Scoping the student-facing side.** Students already see only their own work.

## Risks

- **A missed query is a data leak**, and that is the whole risk of this spec. The `url_map`-driven
  test is the mitigation, and its allowlist is the thing to review most carefully: every name on it
  is a route somebody decided not to scope.
- **This spec already missed 29 routes once.** The first pass counted the `/staff/` console and
  overlooked `workspace_view` entirely, which is the surface where a teacher reads a student's
  actual ledgers rather than their marks. That is the argument for the `url_map` test over a
  hand-written list, made by the spec's own history.
- **Staff reading a student's books is a feature**, not only a leak: `workspace_view` deliberately
  opens archived books to staff and sets a banner naming whose books they are (I2.4). Scoping must
  keep that working for a teacher's own students — the test asserts it does, or the change has
  broken marking rather than secured it.
- **Reporting across sections stops working.** A head of department who wants cohort-wide
  diagnostics now needs an admin account. That is correct but it is a change in what the
  diagnostics screen means, and worth saying to whoever uses it.
- **Deploying this does not fix the leak, and a green deploy will look like it did.** The backfill
  attaches every section to every current staff member on purpose, so nothing breaks — which means
  every teacher still sees everything until an admin prunes. The people screen's count is the only
  thing standing between "shipped" and "fixed".
- **Admin reads everything, and nothing audits it.** There is no per-section grant for admins and no
  record of admin reads. For a handful of departmental staff that is proportionate; it is also the
  thing to revisit first if this tool ever serves more than one department.
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
