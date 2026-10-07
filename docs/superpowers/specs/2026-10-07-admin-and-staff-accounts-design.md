# Admin accounts, and adding teachers in the app

**Date:** 7 October 2026

## Intent

Today a teacher account exists only if somebody runs `flask staff add` on the production dyno.
There is no role above teacher, and no way to take access away from a teacher who leaves. This
adds an admin role, a screen for managing staff, and the ability to deactivate an account.

### What the owner asked for

> there needs to be an admin account and there needs to be a method, in app, for adding teacher
> users

Both, plus three things found while reading that belong with them: there is no deactivation at
all, the audit log records nothing about accounts, and `STAFF_ROLES` is defined twice.

## What is true now

| | |
| --- | --- |
| Roles | `student`, `grader`, `instructor` — a `String(16)` column, default `student` |
| Who counts as staff | `STAFF_ROLES = {grader, instructor}`, defined in **both** `decorators.py:25` and `auth/views.py:47` |
| `grader` vs `instructor` | **No difference.** Nothing in the app branches on which one you are |
| Making a staff account | `flask staff add <email> --role instructor\|grader`. No audit record, no email sent |
| Removing one | Nothing. `flask auth revoke` ends their sessions; they sign straight back in |
| `is_active` | Hardcoded `return True` on `User` |
| Staff route guard | `staff_view` → `abort(404)`, not 403, so a refusal does not confirm the page exists |

## Decisions

- **Admin powers:** manage people, plus the four irreversible operations that already have a
  screen. Teachers keep everything else.
- **Adding a teacher** sends them a sign-in code immediately, reusing the email the app already
  sends.
- **Removing a teacher** deactivates the account: sign-in blocked, record kept.
- **Roles offered** are Teacher and Admin. `grader` is no longer offered.

### Why "dangerous operations" means four things and not more

A CLI command cannot be role-gated: outside a request there is no `current_user`, so shell access
*is* the permission. `packs import`, `packs migrate`, `grade assignment` and `auth revoke` stay
terminal jobs — and a migration that rewrites live student marks is better done deliberately from
a terminal than from a web form. Gating them would mean *building* screens for them, which is its
own project.

Of the fifteen POST routes in the staff console, four are irreversible or cohort-wide:

| Route | Why |
| --- | --- |
| `catalogue_upload` | Every section that later pins that version gets it |
| `grading_release` | There is no un-release, and no guard either |
| `workspace_archive` | Drops a student's book out of grading |
| `section_rotate_code` | Invalidates the code a class is part-way through using |

The other eleven — create and clone an assignment, run grading, override, comment, accommodation,
variant swap, checkpoints, availability, roster import, reopen a book — are the teaching job.

## Section 1: the role and permission model

**`ROLE_ADMIN = "admin"`**, a fourth role. It fits the existing `String(16)` column, so the role
itself needs **no migration** and existing rows are untouched.

`ROLES` gains it too, but be clear about what that does: **`ROLES` is exported and nothing reads
it.** Nothing validates a role against it — `cli.py` hand-writes `click.Choice([ROLE_INSTRUCTOR,
ROLE_GRADER])` instead. So adding admin to `ROLES` keeps the declared set honest and nothing more,
and forgetting it would break no test. The better move while in there is to make the CLI's choice
derive from the one declaration rather than repeat it, which is the same mistake as the duplicated
`STAFF_ROLES` in a smaller form.

**Admins are staff.** `STAFF_ROLES` becomes `{grader, instructor, admin}`, so every route a
teacher reaches today an admin reaches unchanged. Admin is additive.

**One owner for the role sets.** `decorators.py` keeps `STAFF_ROLES` and gains
`ADMIN_ROLES = {admin}`; `auth/views.py` deletes its copy and imports instead. No cycle:
`decorators` imports from `models`, and nothing imports `auth`.

> This is the part worth doing even if nothing else ships. Two definitions of who counts as staff
> is a latent security bug, not untidiness — and duplication of exactly this kind has already
> caused a defect in this codebase.

**`admin_view`** mirrors `staff_view`, including `abort(404)` rather than 403, for the reason
`staff_view` already gives: a refusal that confirms the page exists tells a prober something.

**Templates check the role as well as the routes.** A Release marks button rendered to a teacher
who then meets a 404 is secure and baffling. The route guard is the security boundary; the
template check is so nobody reaches it by accident.

**Bootstrap is the CLI, and that is correct.** `flask staff add <email> --role admin` extends the
existing `--role` choice. The first admin cannot come from inside the app; something has to break
the circle, and shell access is the right thing to require.

**Audit.** `staff_actions` gains `STAFF_INVITED`, `STAFF_ROLE_CHANGED`, `STAFF_DEACTIVATED`,
`STAFF_REACTIVATED`. The CLI writes no audit record today, so moving this in-app gains
traceability rather than spending it.

### Tests

- A teacher gets 404 on each of the four gated routes.
- An admin reaches all fifteen staff routes.
- One test asserts the role sets have collapsed to a single definition, so the duplication cannot
  quietly return.

## Section 2: the people screen, and how a teacher gets in

**`GET /staff/people`**, admin only: one row per staff account — name, address, role, last
sign-in, active or not. Existing `grader` accounts display as **Teacher** with their stored role
noted; nobody's row is rewritten.

**`POST /staff/people`** takes an address, optional names, and Teacher or Admin.

| The address | What happens |
| --- | --- |
| Has no account | Create it with that role, and invite them |
| Has a **student** account | **Refused**, naming the conflict and suggesting a separate staff address |
| Has a staff account already | Say so; do not re-invite. Changing a role is a different action |

The student case is deliberate. One address being both a student with marks and a teacher who can
read every student's marks is an integrity problem, not an inconvenience. A teaching assistant is
the person who will hit this, so the wording has to explain rather than just refuse.

**The invite reuses the existing sign-in email.** `issue_token(..., ip=None)` then
`send_sign_in_email`: the teacher gets a link and a code and is in within a minute. No new
template, no new token type.

`ip=None` is deliberate. The per-IP ceiling is 30 an hour and would throttle an admin adding a
department from one desk; the guard is `if ip_hash:`, so passing none skips exactly the limit that
should not apply here while keeping the per-address limits that protect the recipient. This is the
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

**`issue_staff_code` stays dead.** Wiring it here was considered and rejected: its 30-minute,
no-link code is worse for onboarding than a link. It should be deleted or wired elsewhere, as its
own decision.

### Tests

- Inviting an unknown address creates the account and sends one email.
- Inviting a student's address is refused and creates nothing.
- Inviting an existing staff address does not issue a second token.
- An invite is not subject to the per-IP limit; it is still subject to the per-address limit.
- An admin cannot change their own role; the last admin cannot be demoted.

## Section 3: deactivation

The only schema change: **`deactivated_at: datetime | None`** on `User`. Nullable, no backfill, one
migration.

**`is_active` stops lying** — `return self.deactivated_at is None` in place of `return True`.

**Live sessions die on the next request.** The session loader in `app.py` (which resolves
`public_id:session_epoch`) also returns `None` for a deactivated account. One chokepoint covers
both existing sessions and new ones, which is why it belongs there rather than in a decorator.
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
entire reason for deactivating rather than removing.

**Reactivation** clears the stamp and does not restore sessions; they sign in again.

**Two invariants**, as for the role change: you cannot deactivate yourself, and you cannot
deactivate the last active admin, both checked in the transaction.

**Scope line:** the column is on `User`, so the mechanism is general, but the screen manages staff
only. Deactivating students stays out — they are governed by rosters and sections, which is a
different question.

### Tests

- A valid code from a deactivated account is refused with that message.
- A live session dies on the next request after deactivation.
- The audit trail, overrides and comments survive deactivation.
- Self-deactivation and last-admin deactivation are both refused.
- Reactivation requires a fresh sign-in.
- The request step behaves identically for active, deactivated and unknown addresses — the E1
  guarantee, tested directly.

## Out of scope

- **Gating the CLI.** It cannot be role-gated; see above.
- **Pack operations in the app** (import, diff, migrate as admin screens). Its own spec, after this.
- **Giving `grader` real limits.** Deliberately declined: it would mean a permission decision on
  every existing staff route, which is most of the work and none of the ask.
- **Deactivating students.**
- **A dedicated invite email** with a multi-day token.
- **Self-service password or profile management.** There are no passwords; sign-in is by emailed
  code.

## Risks

- **Locking out the only admin.** The two invariants are the guard, but a single admin who loses
  their mailbox still needs `flask staff add` to recover. That is the break-glass path and it
  should stay documented, not removed.
- **The 15-minute invite link** will read as broken to a teacher who opens it the next day. The
  flash message on the people screen should say the link is short-lived and that signing in works
  regardless.
- **A teaching assistant with one address.** The student-account refusal is correct but will be
  met by real people; if it becomes common, the answer is a decision about whether one person may
  hold two roles, not a loosening of the check.
- **`release_marks` still has no guard.** Making it admin-only narrows who can fire it but does not
  stop a half-graded release. Worth fixing, separately.
