# Parchment — status 3

_2026-09-18 · 26 commits · ~270 Python tests + JavaScript tests · ruff clean · running live
against Neon Postgres._

An enumeration of what is built and what is not, step by step, against
[`../Riverbend-Ledger-PRD-Flask.md`](../Riverbend-Ledger-PRD-Flask.md). Companion to
[`STATUS.md`](STATUS.md) and [`status2.md`](status2.md); this file is the plain done/not-done list.

## One-paragraph state

A student can run the **entire December cycle** for real: sign in by emailed magic link or code →
join a section (or choose a company for a choice assignment) → triage documents → journalise →
post to the general and subsidiary ledgers → adjust → self-check with checkpoints → build the
financial statements → close → submit. The **grading engine** marks all ten components on the
student's own figures, names the designed errors, and proves A2/A3/A9. The **staff console**
sets up a term, grades a section in batches with overrides and released marks, shows diagnostics,
and takes generated pack zips (images included). Multi-company, the no-loss save protocol, and the
offline pack generator are in. What remains is deployment/CI, a few JavaScript enhancements, some
staff/ops odds and ends, and the accessibility/hardening pass.

---

## DONE

### Phase 0 — generator and packs
- [x] Pure ledger engine (`money`, `messages`, posting/balances/trial-balance/subsidiary proof)
- [x] Pack schema (pydantic) + validation rules **V1–V16, W1** (V9 replay, V12 images, V14
      catalogue, V16 zip safety)
- [x] Pack zip reader + importer (`import_content`, `import_answer_keys`) + `replay.py`
- [x] **Offline generator** (`generator/`): computes the answers by replaying the authored entries
      through the engine, renders one PNG per document per variant (Pillow), writes the pack zip;
      `scripts/generate_pack.py` CLI
- [x] TestCo Alpha fixture (finished pack + authoring source)

### Phase 1 — deployed skeleton and engine
- [x] Flask app factory, config (pooler-safe engine, scheme normalisation), extensions
- [x] Security headers + CSP nonce, honest error pages, `/healthz`
- [x] Models: people / content / work with **D5 composite scoping keys**
- [x] Migrations (9), first one carries the **balance trigger** + role-guarded default privileges
- [x] `ledger/snapshot.py` (DB→engine loader); **A2 proven two ways** (DB replay + pure V9)
- [x] Structural guard tests from day one (import boundaries, route decoration, no inline styles)

### Phase 2 — journals, posting, saving
- [x] Special + general journal storage; money parsing; validators
- [x] Write path `workspace_write` (row lock, gates, version bump, activity, commit once)
- [x] Record entry (idempotent), void, post general, post subsidiary (single + all), reverse
- [x] Journal UI (list, journal page, entry grid — works without JavaScript)
- [x] **`save.js`** — the no-loss protocol (retry, stale-tab, restore); JS tested under node
- [x] A4 (out-of-balance refused + DB rejects), A5 (designed errors save), A26 (no lost work)

### Phase 3 — documents
- [x] Document queue + dispositions (record / no-entry-with-reason, superseded not deleted)
- [x] Document detail with the "view as text" table and guidance
- [x] **Screen mode**: images in Postgres (`pack_asset`), authorised image route, `zoom.js`
- [x] Join codes + enrolment; workspace chrome, home page

### Phase 4 — the rest of the cycle
- [x] Trial balances (unadjusted / adjusted / post-closing); adjusting + closing entries
- [x] **Statement builder** with subtotal types from the pack (structure + figures)
- [x] Checkpoints (attempts, pass/locked) — answer read only in `grading.checkpoints.evaluate` (A8)
- [x] Submission + late policy (`late_hours` stamped, read-only after)

### Phase 5 — grading engine
- [x] Pure `grade(snapshot, pack, key)` + all **ten components** on the student's own figures
- [x] Document-level error **signatures** + balance-delta fallback
- [x] Review flags, batching, time-on-task; **A3, A9, A10, A11** (engine + through the database)
- [x] Grades stored: immutable runs, overrides with reasons that survive a regrade (**A12**),
      released marks the student can see

### Phase 6 — staff console
- [x] Assignments (create fixed **or choice**, clone with shifted dates, join codes, sections)
- [x] Progress, Grading (batched run, per-item evidence, overrides, comments, release)
- [x] Diagnostics (designed errors made by the cohort, time on task) + CSV export
- [x] Catalogue: pack **zip upload** with every rule checked before writing

### Phase 7 — multi-company
- [x] `section_pack_availability` (M1.4) + `assignment_choice` (tension 4)
- [x] Student **company choice** (`/a/<assignment>/choose`), home prompt, **switch menu**
- [x] Staff **availability screen** (make available / withdraw); **A22** (withdraw leaves open
      books usable)
- [x] **Workspace archive + restart** (I1.12) — old stays viewable, fresh one opens
- [x] **Pack migration** — `flask packs migrate` (dry-run + one-transaction remap by natural key,
      refuses if used content is gone) + `flask packs import`

### Auth, CLI (cross-cutting)
- [x] **Magic-link + six-digit-code** sign-in (T9, E1–E4): scanner-safe GET, single-use, 5-attempt
      lock, table-counted rate limits, `login_token` stores only hashes, 30-day purge
- [x] Email module (console / Resend one-POST / memory); sessions (14-day keep, `basic` protection)
- [x] CLI: `staff add`, `auth issue-link`, `auth revoke`, `packs import`, `packs migrate`
- [x] `scripts/clean_testco.py` (dev-DB fixture cleanup)

---

## NOT DONE

### Phase 2/3 — JavaScript enhancements
- [ ] `entry-grid.js` — live in-cents totals, add/remove lines, keyboard map (grid works without it)
- [ ] `picker.js` — ARIA 1.2 combobox for accounts/documents, incl. the **M3.6** cross-company
      filter message (native `<select>` works today)
- [ ] `batch.js` — client batching for section grading (server batching + CLI exist)
- [ ] **Special-journal column entry form** (recording currently uses the general-journal grid)

### Phase 4 — remainder
- [ ] Worksheet (`worksheet_cell`) — cut-list item #1
- [ ] Checkpoint **stage-gating** and per-assignment checkpoint config (`assignment_checkpoint`)
- [ ] Per-student **accommodations** (`assignment_override`: extended due date / checkpoint deadline)

### Phase 6 — staff remainder
- [ ] Staff-issued sign-in code **UI** (I2.6) — `issue_staff_code` service exists, no screen yet
- [ ] Reopen a submitted workspace; grant extra checkpoint attempts (`checkpoint_grant`)
- [ ] **Print** record (`print/workspace.html`) and answer-key print, saved as PDF by the browser
- [ ] I2.5 (show last attempted save, incl. refused) surfaced on the staff view

### Phase 8 — hardening (not started)
- [ ] Screen-reader pass; Playwright accessibility + no-loss tests (A17, A18)
- [ ] Print stylesheets; backup script + restore drill (A27); due-date runbook (OPS-3)
- [ ] Failure banners polish; Sentry (OPS-1, optional)

### Auth / ops / delivery (not started)
- [ ] **Resend** production setup: verified sending domain (SPF/DKIM/DMARC), campus allow-listing
- [ ] **Heroku**: `Procfile`, `gunicorn.conf.py`, release-phase migrations, staging→prod pipeline
- [ ] **CI** (`.github/workflows`): ruff → CSS rebuild check → migrate + privilege check → tests →
      guards → golden tests (must run serially; the DB suite self-collides if parallel)
- [ ] `requirements.txt` compiled with hashes
- [ ] Remaining CLI: `packs validate`, `grade assignment`, `export marks`, `seed staging`,
      `purge section`, `replay-key`

### Generator remainder
- [ ] Printable PDFs for paper mode
- [ ] Real `riverbend-supply` pack + `testco-beta` fixture

### Guards not yet dedicated
- [ ] A7 full banned-words sweep (partial: checked over rendered student screens)
- [ ] A8 dynamic key-leak sweep (partial: proven for checkpoints)
- [ ] A21 no-account-number-literals scan
- [ ] A20/A23 dedicated isolation + coexistence tests (partial: composite-FK rejection proven)

---

## Acceptance criteria

| # | Criterion | Status |
| --- | --- | --- |
| A1 | Full December cycle unaided | Reachable end to end (pilot pending) |
| A2 | Replay balances/matches to the cent | **Done** (auto) |
| A3 | Replay scores full marks | **Done** (auto) |
| A4 | Out-of-balance cannot be saved; DB rejects bypass | **Done** |
| A5 | Designed errors save with no warning | **Done** |
| A6 | Trial balance on errors reads "In balance" | **Done** |
| A7 | No banned words in the student interface | Partial (render checks) |
| A8 | No answer-key value reaches a student | Partial (checkpoints proven) |
| A9 | One early error → still ≥ 85% | **Done** (auto) |
| A10 | Each designed error named, per signature | **Done** |
| A11 | Section of 40 grades < 30 s, none > 10 s | **Done** (auto) |
| A12 | Override changes mark, survives regrade | **Done** |
| A13 | Create assignment/join/student < 5 min | **Done** (screens) |
| A14 | Clone with new dates < 1 min | **Done** |
| A15 | Regenerated pack uploads without hand-editing | **Done** (generator → upload) |
| A16 | Marks CSV imports to the LMS | Partial (generic CSV export exists) |
| A17 | Every workflow by keyboard alone | Not verified (Phase 8) |
| A18 | Server killed mid-entry loses nothing | Partial (save.js + tests; Playwright pending) |
| A19 | A2 for every catalogue company | **Done** (per pack) |
| A20 | Companies cannot reach each other | Partial (composite FK proven) |
| A21 | No account-number literals in code | Not enforced by a guard yet |
| A22 | Disabling a company leaves work usable | **Done** |
| A23 | Two charts with account 101 coexist | Partial (scoping in place) |
| A24 | Student always knows the company | **Done** (chrome) |
| A25 | Sign-in survives the real world | Partial (scanner-safe + code; email deliverability pending) |
| A26 | No lost work | **Done** (save.js + tests) |
| A27 | Recovery proven (restore, pg_dump) | Not started (Phase 8) |
| A28 | Late policy holds; unsubmitted graded | **Done** |
| A29 | Built CSS matches a fresh build | **Done** (committed; CI check pending) |
| A30 | Largest pack uploads < 25 s (or CLI) | CLI import exists; timing not measured |

---

## Notes and deferrals
- **Recording uses the general-journal grid** for now; the special-journal column form is deferred
  (engine + posting already handle special journals).
- **V9 replays only `independent` adjustments** (their amount is in the key); `dependent` ones are
  scored against the student's own base figure (tension 8).
- **Do not run the DB suite in parallel** against the shared Neon database — concurrent runs seed
  the same fixture slugs and collide. Run serially; `scripts/clean_testco.py` clears leftovers.
- **Email provider is Resend** (the PRD's "Render" cannot send mail); only `auth/email.py` + four
  config vars change if that's wrong.
