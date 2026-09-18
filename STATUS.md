# Parchment — build status

_Last updated: 2026-09-18 · 16 commits · 219 tests passing · ruff clean · running live against Neon._

This tracks what is built and what is not, against the phases in
[`../Riverbend-Ledger-PRD-Flask.md`](../Riverbend-Ledger-PRD-Flask.md). It is a companion to the
[README](README.md).

## TL;DR

A student can complete the **full December cycle** end to end: sign in → triage documents →
journalise → post to general and subsidiary ledgers → record adjusting entries → self-check with
checkpoints → record closing entries → view all three trial balances → **build the statements the
pack defines** → submit. Everything is company-scoped, every ledger figure is **derived by the
engine** (never stored), and the **A2** guarantee (the engine reproduces the answer key to the
cent) is proven two independent ways.

The **grading engine** marks all ten components on the student's own figures, names the designed
errors, and proves the two tests that protect the design: **A3** (work that follows the key earns
full marks) and **A9** (one mis-journalised document, handled properly afterwards, still scores
88.3%).

Grading results are **stored** now: a run is immutable, an override carries a reason and survives
a regrade (**A12**), and a student sees their marks once the instructor releases them. What is
missing is the rest of the instructor's side of it. The console now covers **Assignments**,
**Progress**, **Grading** and **Diagnostics**: an instructor grades a section in batches, reads
what the rule credited item by item, overrides a mark with a reason, releases marks in one action,
and sees which designed errors the cohort actually made, which documents were handled differently
from the key, and how long the work took — with the whole cohort exportable as CSV. **A term can
now be set up entirely through screens**: a section with a join code, an assignment on a company
from the catalogue, cloning last term's with the dates moved, and a student who types the code and
lands in their own books. **Packs arrive as zips now**: the catalogue takes the archive the
generator makes, checks it against every rule before writing anything, and refuses a repeat upload
or a version that is not newer. The multi-company UI, the JavaScript layer (`save.js`/pickers),
real magic-link auth, document images, deployment config and CI are what remain. Details below.

## How to run and test

```bash
cd parchment
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"          # or: pip install Flask Flask-SQLAlchemy Flask-Migrate \
                                 #        Flask-Login Flask-WTF SQLAlchemy "psycopg[binary]" \
                                 #        pydantic requests pytest ruff
pytest                           # 219 tests; DB tests hit Neon (creds in .env, gitignored)
ruff check parchment tests

# migrations run through the direct Neon endpoint:
export FLASK_APP=parchment.app:create_app PARCHMENT_USE_DIRECT_DB=1
flask db upgrade

# rebuild the committed Tailwind CSS:
./bin/get-tailwind.sh
./bin/tailwindcss -i parchment/static/src/app.css -o parchment/static/dist/app.css --minify
```

---

## Done

### Engine and content (pure, no Flask/DB)
- [x] `money.py` — integer-cent parse/format, reason-coded errors (T7.1, D6 rule 1)
- [x] `messages.py` — student-facing strings; no "correct/incorrect/right/wrong" (A7)
- [x] `ledger/` — pure engine: posting derivation (special-journal column totals/individuals,
      general), debit-positive balances, trial balances by stage, subsidiary proof (T6.2–T6.4)
- [x] `ledger/snapshot.py` — the one DB→engine loader (bounded queries)
- [x] `packs/schema.py` — pydantic schema for `pack.json` + answer keys (T5.2/T5.3)
- [x] `packs/validate.py` — rules **V1–V11, V13, V15** (V12 and W1 wait on images and pack text);
      each problem carries its JSON path, and an upload reports every problem at once
- [x] `packs/zip_reader.py` — opens the generator's zip with the **V16** safety rules: no path
      that escapes the archive, no more than 2,000 entries or 200 MB unpacked, and a checksum
      over the bytes
- [x] `packs/importing.py` — validate, then **V14** against the catalogue (the same archive twice
      is refused, and a version must be newer than every version already held), then write
- [x] `packs/replay.py` — pure `pack+key → Snapshot`, generates closing entries (for V9)
- [x] `packs/importer.py` — `import_content` + `import_answer_keys`
- [x] **A2 proven two ways**: DB replay (`tests/integration/test_a2.py`) and pure V9
      (`tests/unit/test_replay.py`), both to the cent

### Database and app skeleton
- [x] SQLAlchemy models: people / content / work core chain with **D5 composite scoping keys**
- [x] Migrations (4): initial schema with the **balance trigger** + role-guarded default
      privileges + deferrable composite FKs; `activity_event`; `answer_key` +
      `checkpoint_attempt`; `statement_draft` + `statement_line` (with `DELETE` granted to the
      web role, since a saved statement replaces its rows)
- [x] `config.py` (pooler-safe engine, scheme normalisation), `extensions.py`, `app.py` factory,
      `security.py` (CSP + nonce, HSTS/nosniff), `errors.py` (honest error pages), `/healthz`
- [x] **D5 constraints proven against real Postgres**: balance trigger rejects unbalanced (A4),
      composite FK rejects cross-company account (A20)

### Student experience
- [x] Tailwind v4 (standalone CLI, pinned + checksummed; committed `dist/app.css`, A29)
- [x] Templates: base shell, workspace layout (company chrome, nonce'd accent), auth layout, macros
- [x] `decorators.workspace_view` (T3.3): sign-in, load-excluding-archived, 404-not-403,
      company-slug mismatch page
- [x] Read screens: home, overview (with triage progress), trial balance (3 stages), general
      ledger, subsidiary proof
- [x] **Write path** `services/workspace_write` (T3.4): row lock, gates, version bump, activity,
      commit once, rollback+reraise
- [x] `forms/entries.py` — parse+validate a general-journal entry (balance, one-side, chart,
      control-line party, document, period, money)
- [x] Services: `record_entry` (idempotent on `client_key`), `void_entry`, posting (general,
      subsidiary single + all), `reverse_run`, `set_disposition`, `record_attempt`, `submit_workspace`
- [x] Journal UI: journals list, journal page (entries, post/void/reverse), entry grid form (no JS)
- [x] Documents + dispositions: queue, detail (view-as-text from pack, guidance), record / no-entry
- [x] Checkpoints: `grading/checkpoints.py` `evaluate` returns **boolean only** (A8); attempts /
      remaining / locked; submit-a-figure UI
- [x] **Statement builder** (S5.5, tension 7): `statement_draft`/`statement_line` with composite
      scoping keys and CHECKs; rows are heading / account / subtotal / total / blank; subtotal and
      total rows take their **type from the pack**, headings stay free text; figures are typed by
      the student (parentheses mean a negative, as on paper) and the app does no arithmetic; the
      side panel shows the student's **own** adjusted balances; saving replaces the layout and
      bumps the draft version
- [x] Submission: submit → `late_hours` stamped (no penalty), then read-only; the checklist counts
      statements started
- [x] Dev-only sign-in (email → session; refused in production)

### Grading engine (phase 5)
- [x] Pure `grade(work, pack, key)` over dataclasses — no Flask, no queries (T8.1)
- [x] All **ten components** (T8.2): triage, journal_selection, entry_accuracy (structure and
      figures split, lines merged by account/party/side so a split line is not a mistake),
      posting_completeness, subsidiary_agreement, adjustment_form, adjustment_amounts
      (`independent` figures marked, `dependent` ones left to the grader with the student's own
      base balance), statements_structure, statements_figures, closing
- [x] Evidence per item (what the student did, what the rule credited) and review flags (I3.2/I3.3)
- [x] **Error signatures** (T8.5): document-level detection first (`entry_line`, `entry_amount`),
      balance-delta fallback reported as a possibility, and differences no signature explains
      listed for the instructor. Vacuous credit on empty books is refused — nothing recorded is
      not a cleared account, and nothing recorded is not a designed error
- [x] A statement's stage (`adjusted` / `post_closing`) comes from the **pack**, not a hardcoded
      statement type name
- [x] `grading/workspace.py`: the one DB→engine loader for grading, and the only place besides
      `checkpoints` that reads an answer key (D6 rule 6)
- [x] Differences no signature explains are returned as `GradeResult.unexplained`, for the
      instructor to read
- [x] **Golden tests A3 and A9** (`tests/golden/`): a faithful replay scores 100/100; one
      mis-journalised document, handled properly afterwards, scores 88.3%
- [x] **A9 through the database** as well: the same helper with one document mis-journalised —
      the mistake costs marks where it was made and nowhere else, read back out of Postgres
- [x] **A3 through the database**: `tests/perfect_student.py` builds a student who followed the
      key using the same services a browser drives — triage, entries in the key's journals with
      their special-journal columns, posting to both ledgers, the adjustment, the closing entries
      worked out from their own adjusted balances, and a statement built from their own figures —
      and grading reads it back out of Postgres for full marks. Restoring the document-reference
      bug drops that student to 68/100, so the guard bites
- [x] **Grade storage**: `grade_run` (immutable, one per run, with the evidence as JSON and how
      the work was handed in), `grade_override` (a reason is required, one current row per
      component, and it is applied on top of the latest run so **A12** holds), `grade_comment`
- [x] Points are stored in hundredths of a point, as money is stored in cents (D1)
- [x] Student **Marks** screen: nothing until the instructor releases the section, then the marks
      awarded per component, any instructor's reason, and the comment (S6.6): a faithful replay scores 100/100; one
      mis-journalised document, handled properly afterwards, scores 88.3%

### Instructor console (phase 6, begun)
- [x] `staff/` blueprint with `staff_view` (404, not 403, for anyone else) and a guard test that
      every `/staff/` route carries it
- [x] **Assignments** screen: each assignment with its section, company, mode and student count
- [x] **Progress** screen (I2.1–I2.3, I2.5): stage reached, documents handled, journals posted,
      how the work was handed in, last activity, checkpoint lockouts **with the figures
      submitted**, and the **last refused save** with its document and the message the student
      saw. Six bulk queries for a whole section, nothing stored
- [x] Refused saves are recorded where they happen, so "who is stuck, and on what?" has an answer
      the paper set could never give (`services/activity.py`)
- [x] Opening a student's workspace read-only names whose books they are, on every page (I2.4)
- [x] **Grading** screen (I3.1–I3.7): marks per student, "needs a look" filter for the review
      queue, grading in batches of 10 per request so nothing nears the request limit, a detail
      screen showing each component's evidence and the designed errors recognised, override with
      a required reason, comment, and release marks for the section in one action
- [x] `staff_action` audit trail (D2): every override, comment, run and release is recorded with
      the reason given at the time and no personal data
- [x] **Diagnostics** (I4.1–I4.3, I4.5): how many students each designed error caught (and how
      many the balances only suggest it for), which documents were handled differently from the
      key and in which direction, and time on task with its median, quartiles and distribution.
      Bars are `<meter>` elements, because the content security policy forbids inline styles
- [x] **Time on task** (T8.7) as a pure rule: gaps over twenty minutes are breaks worth nothing,
      so a tab left open overnight adds nothing
- [x] **Setting a term up** (I1.1–I1.6, A13, A14): make a section (join code generated from an
      alphabet with no O/0 or I/1), make an assignment on a catalogue company with its mode,
      dates, late policy and variant policy, and clone last term's with every date moved by one
      offset. Times are read in the course's own time zone
- [x] **Join codes** (I1.4): a student types the code, is enrolled, and gets one workspace per
      open assignment with a variant handed out in turn. Joining twice changes nothing; a code
      that is not in use says only that; rotating a code retires the old one
- [x] **Catalogue** screen (I1.7, I1.10): every company, its versions, period, scope tags, whether
      it carries images, and how many workspaces sit on each version — with the upload form and
      the refusal listing every problem by rule and path
- [x] **Cohort CSV export** with a stable header: one row per student, every component, the time
      on task and the signatures recognised

### Guards and tests (219 in all)
- [x] Import-boundary guard: `ledger/` stays pure (T3.1)
- [x] Structure guards: every `/w/` route uses `@workspace_view`; no inline `style`/handlers (T11)
- [x] Partial A7 (banned words over rendered student screens), partial A8 (checkpoint answer never
      in a response), money round-trips/rejections
- [x] Integration (live Neon): D5 constraints, DB A2, write path, dispositions, checkpoints,
      submit, statement drafts
- [x] **Route-level harness** (`client` fixture): Flask-SQLAlchemy is bound to the test
      connection, so a real request writes inside the test transaction and nothing persists. The
      statement screens are tested through the same form endpoints a browser uses, including the
      404 for another student's workspace and the 422 that keeps every typed row on the page.
      This is the harness the full A7/A8 sweeps and A26 will need

---

## Not done

### Phase 0 — generator and packs
- [ ] Generator script (workbook → pack zip + one PNG per document per variant)
- [ ] Validation rules **V12** (images) and **W1** (pack text warnings) — both wait on images
- [ ] Image entries in a zip are read but not stored: `pack_asset` / `document_variant` do not
      exist yet, so a screen-mode pack loads as a paper one
- [ ] `testco-beta` fixture and the real `riverbend-supply` pack (only `testco-alpha` exists)

### Phase 2 — journals (partial)
- [ ] **Special-journal column entry form** (columns → lines). Recording currently uses the
      general-journal grid; the engine and posting already handle special journals
- [ ] JavaScript: `save.js` (no-loss protocol, T7.4 — **A26**), `entry-grid.js` (live cents totals,
      add/remove lines), `picker.js` (ARIA combobox for accounts/documents, M3.6), `zoom.js`,
      `batch.js`. Everything currently works **without** JavaScript

### Phase 3 — documents (partial)
- [ ] Document **images** (screen mode): image bytes route, zoom/pan, **V12**
- [ ] Guided mode gating and the M3.6 cross-company picker message
- [ ] Join codes / enrolment UI (join flow, roster CSV)

### Phase 4 — statements (mostly done)
- [ ] `statements[].stage` is read by the app and by grading but is **not validated** yet (V4 only
      checks sections and subtotal types)
- [ ] Reordering rows with Move up / Move down buttons (rows are currently ordered by where they
      sit in the form; a saved row can be retyped but not moved)
- [ ] Worksheet (`worksheet_cell`) — optional (cut list #1)
- [ ] Checkpoint **stage-gating** (needs `assignment_checkpoint`; e.g. "pass cp2 before adjusting")
- [ ] Per-student accommodations (`assignment_override`)

### Phase 5 — grading (engine and storage done, instructor screens not)
- [ ] Batching (T8.6), time-on-task (T8.7), the review queue and releasing marks — all need the
      staff console
- [ ] `error_signatures[].deduct_points` is carried in the schema but ignored by the engine;
      signatures are diagnostic only so far (T8.5)
- [ ] Golden tests **A10** (every signature named, per signature) and **A11** (40 workspaces
      under 30 s)

### Phase 6 — staff console (Assignments, Progress, Grading and Diagnostics done)
- [ ] I4.4 (where students abandoned) and I4.6 (comparing a cohort across two companies) — both
      **Should** in the PRD
- [ ] Checkpoint deadlines, per-student accommodations and roster CSV import (I1.5, I1.11) — the
      tables exist for accommodations, the screens do not
- [ ] Assigning a variant by hand where the policy says manual (I1.3)
- [ ] Exports (CSV presets), print record, staff-issued sign-in codes
- [ ] Grading a section larger than one batch needs the button pressed again; `batch.js` will
      automate it (T8.6)

### Phase 7 — multi-company (schema ready, UI not)
- [ ] Catalogue + pack upload UI, `section_pack_availability`, student company choice, switch
      confirmation, workspace archive, pack migration
- [ ] Guards **A19, A22, A23** (A20 isolation partly covered)

### Phase 8 — hardening (not started)
- [ ] Screen-reader pass, Playwright a11y + no-loss tests (A17, A18)
- [ ] Failure banners wired to `save.js`, print stylesheets / PDF record, backup script, restore
      drill, due-date runbook

### Auth, ops, delivery (not started)
- [ ] Real **magic-link + six-digit-code** sign-in, Resend module, rate limits, staff-issued codes,
      `session_epoch` revoke CLI (E1–E6). Current sign-in is dev-only
- [ ] CLI commands: `staff add`, `packs validate/import/migrate`, `grade`, `export marks`,
      `seed staging`, `purge`, `auth issue-link/revoke`, `replay-key`
- [ ] Heroku: `Procfile`, `gunicorn.conf.py`, release phase, staging/prod pipeline
- [ ] CI (`.github/workflows`): ruff, CSS rebuild check, migrate + privilege check, tests, guards,
      golden tests
- [ ] `requirements.txt` compiled with hashes

---

## Acceptance criteria coverage

| # | Criterion | State |
| --- | --- | --- |
| A2 | Replaying the key balances and matches to the cent | **Done** (DB + pure V9, auto) |
| A3 | Work that follows the key earns full marks | **Done** (golden, twice: pure engine and through the database, auto) |
| A4 | Out-of-balance entry cannot be saved; DB rejects bypass | **Done** (validator + trigger) |
| A6 | Trial balance on designed errors reads "In balance" | **Done** (always balances by construction) |
| A7 | No banned words in the student interface | **Partial** (render checks; full sweep pending) |
| A8 | No answer-key value reaches a student | **Partial** (checkpoints proven; full leak test pending, harness now exists) |
| A9 | One early mistake, handled properly afterwards, scores ≥ 85% | **Done** (88.3%, golden, twice: pure engine and through the database, auto) |
| A10 | Each designed error is named by its label | **Partial** (detection tested per type; a case per signature pending) |
| A12 | An override changes the mark and survives a regrade | **Done** (auto) |
| A13 | A section, an assignment, a join code and an enrolled student, without documentation | **Partial** (the whole path is tested end to end through the screens; the five-minute timing is still to be observed on a real person) |
| A14 | Cloning an assignment with new dates takes under 1 minute | **Partial** (one form, one field, tested; timing still to be observed) |
| A20 | Two companies' workspaces cannot reach each other | **Partial** (composite-FK + 404 proven; full A20 pending) |
| A23 | Two charts with account 101 coexist everywhere | **Partial** (scoping in place; dedicated test pending) |
| A26 | No lost work (expired session, retry, deploy) | **Not done** (needs `save.js`) |
| A28 | Late policy holds; unsubmitted graded as "Not submitted" | **Done** (`late_hours` on submit; each run records open / submitted / submitted_late / not_submitted) |
| A29 | Built CSS in git matches a fresh build | **Done** (committed; CI check pending) |
| A15 | A regenerated pack uploads without hand-editing | **Partial** (a pack zip uploads, validates and lands in the catalogue; images are not stored yet) |
| A1, A5, A11, A16–A19, A21, A22, A24, A25, A27, A30 | — | **Not yet** (need the generator, JS, deploy, images) |

---

## Key decisions and limitations
- **Email provider is Resend** (the PRD's request said "Render", which cannot send email). Only
  `auth/email.py` + four config vars change if that's wrong.
- **Recording uses the general-journal grid** for now (regular/adjusting/closing). A credit sale
  can be recorded there (AR + party, Sales) so the full posting/subsidiary flow is demoable; the
  special-journal column form is deferred.
- **Statement figures are typed by the student** (tension 6). The builder shows their own adjusted
  balances beside the form, and nothing is added up for them. Subtotal rows name a type from the
  pack (tension 7) so grading can read the structure without parsing free text.
- **The ledger snapshot carries each entry's document reference.** Without it every component that
  works document by document scored zero on real data while the in-memory golden tests passed.
  A3 now runs through the database as well, and that guard was mutation-checked: put the bug back
  and the perfect student scores 68 instead of 100.
- **The database harness lives in `tests/conftest.py`**, not under `tests/integration/`, because
  the golden tests need it too.
- **Grading refuses vacuous credit.** Books with nothing in them agree with themselves and hold no
  open temporary accounts; the engine says so rather than awarding the marks, and skips signature
  detection entirely (an untouched workspace would otherwise match any signature naming accounts
  it never touched).
- **V9 replays only `independent` adjustments** (their amount is in the key). A pack whose balances
  depend on a `dependent` adjustment is skipped by V9 and left to grading against the student's own
  figures (tension 8).
- **Two-role least privilege** (`riverbend_app` / `riverbend_migrator`) is guarded in the first
  migration so it's a no-op on the single-role dev Neon database and correct in production.
- **DB tests require real Postgres** (Neon); the harness uses `join_transaction_mode="create_savepoint"`
  so the committing write path still rolls back and nothing persists.
- **The route harness gives the app the test's own session** (`db.session.registry.set`). Two
  sessions on one connection each managing savepoints fight, and the loser is a teardown that
  cannot roll back.
