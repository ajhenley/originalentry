# Parchment — build status

_Last updated: 2026-09-17 · 7 commits · 80 tests passing · ruff clean · running live against Neon._

This tracks what is built and what is not, against the phases in
[`../Riverbend-Ledger-PRD-Flask.md`](../Riverbend-Ledger-PRD-Flask.md). It is a companion to the
[README](README.md).

## TL;DR

A student can complete the **full December cycle** end to end: sign in → triage documents →
journalise → post to general and subsidiary ledgers → record adjusting entries → self-check with
checkpoints → record closing entries → view all three trial balances → submit. Everything is
company-scoped, every ledger figure is **derived by the engine** (never stored), and the **A2**
guarantee (the engine reproduces the answer key to the cent) is proven two independent ways.

Not yet built: the statement builder, the grading engine, the staff console, the multi-company UI,
the JavaScript layer (`save.js`/pickers), real magic-link auth, document images, deployment
config, and CI. Details below.

## How to run and test

```bash
cd parchment
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"          # or: pip install Flask Flask-SQLAlchemy Flask-Migrate \
                                 #        Flask-Login Flask-WTF SQLAlchemy "psycopg[binary]" \
                                 #        pydantic requests pytest ruff
pytest                           # 80 tests; DB tests hit Neon (creds in .env, gitignored)
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
- [x] `packs/validate.py` — rules **V1–V4, V6, V7, V9, V10, V13, V15**; each problem with its JSON path
- [x] `packs/replay.py` — pure `pack+key → Snapshot`, generates closing entries (for V9)
- [x] `packs/importer.py` — `import_content` + `import_answer_keys`
- [x] **A2 proven two ways**: DB replay (`tests/integration/test_a2.py`) and pure V9
      (`tests/unit/test_replay.py`), both to the cent

### Database and app skeleton
- [x] SQLAlchemy models: people / content / work core chain with **D5 composite scoping keys**
- [x] Migrations: initial schema with the **balance trigger** + role-guarded default privileges +
      deferrable composite FKs; `activity_event`; `answer_key` + `checkpoint_attempt`
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
- [x] Submission: submit → `late_hours` stamped (no penalty), then read-only
- [x] Dev-only sign-in (email → session; refused in production)

### Guards and tests (80)
- [x] Import-boundary guard: `ledger/` stays pure (T3.1)
- [x] Structure guards: every `/w/` route uses `@workspace_view`; no inline `style`/handlers (T11)
- [x] Partial A7 (banned words over rendered student screens), partial A8 (checkpoint answer never
      in a response), money round-trips/rejections
- [x] Integration (live Neon): D5 constraints, DB A2, write path, dispositions, checkpoints, submit

---

## Not done

### Phase 0 — generator and packs
- [ ] Generator script (workbook → pack zip + one PNG per document per variant)
- [ ] Zip import path: streaming to temp file, **V16 zip safety**, PNG signature checks (importer
      currently consumes a validated dict, not a zip)
- [ ] Validation rules **V5, V8, V11, V12, V14, W1** (registered in `validate.DEFERRED_RULES`)
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

### Phase 4 — statements (partial)
- [ ] **Statement builder**: `statement_draft` / `statement_line` tables, subtotal types from the
      pack, the builder UI (the large remaining Phase 4 piece)
- [ ] Worksheet (`worksheet_cell`) — optional (cut list #1)
- [ ] Checkpoint **stage-gating** (needs `assignment_checkpoint`; e.g. "pass cp2 before adjusting")
- [ ] Per-student accommodations (`assignment_override`)

### Phase 5 — grading engine (not started)
- [ ] Pure `grade(snapshot, pack, key)` + the **ten components** (T8.2)
- [ ] Document-level error **signatures** + balance-delta fallback (T8.5)
- [ ] Review flags, grade overrides/comments, batching (T8.6), time-on-task (T8.7)
- [ ] Golden tests **A3, A9, A10, A11**

### Phase 6 — staff console (not started)
- [ ] Assignments (create, clone, checkpoints, accommodations, late policy, join codes, roster)
- [ ] Progress, Grading (overrides, comments, release), Diagnostics, exports (CSV presets), print,
      staff-issued sign-in codes, `staff/` blueprint + `staff_action` audit

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
| A4 | Out-of-balance entry cannot be saved; DB rejects bypass | **Done** (validator + trigger) |
| A6 | Trial balance on designed errors reads "In balance" | **Done** (always balances by construction) |
| A7 | No banned words in the student interface | **Partial** (render checks; full sweep pending) |
| A8 | No answer-key value reaches a student | **Partial** (checkpoints proven; full leak test pending) |
| A20 | Two companies' workspaces cannot reach each other | **Partial** (composite-FK + 404 proven; full A20 pending) |
| A23 | Two charts with account 101 coexist everywhere | **Partial** (scoping in place; dedicated test pending) |
| A26 | No lost work (expired session, retry, deploy) | **Not done** (needs `save.js`) |
| A28 | Late policy holds; unsubmitted graded as "Not submitted" | **Partial** (submit + late_hours; grading pending) |
| A29 | Built CSS in git matches a fresh build | **Done** (committed; CI check pending) |
| A1, A3, A5, A9–A19, A21, A22, A24, A25, A27, A30 | — | **Not yet** (need grading, staff, JS, deploy, packs) |

---

## Key decisions and limitations
- **Email provider is Resend** (the PRD's request said "Render", which cannot send email). Only
  `auth/email.py` + four config vars change if that's wrong.
- **Recording uses the general-journal grid** for now (regular/adjusting/closing). A credit sale
  can be recorded there (AR + party, Sales) so the full posting/subsidiary flow is demoable; the
  special-journal column form is deferred.
- **V9 replays only `independent` adjustments** (their amount is in the key). A pack whose balances
  depend on a `dependent` adjustment is skipped by V9 and left to grading against the student's own
  figures (tension 8).
- **Two-role least privilege** (`riverbend_app` / `riverbend_migrator`) is guarded in the first
  migration so it's a no-op on the single-role dev Neon database and correct in production.
- **DB tests require real Postgres** (Neon); the harness uses `join_transaction_mode="create_savepoint"`
  so the committing write path still rolls back and nothing persists.
