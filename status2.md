# Parchment — everything done and not done

_2026-09-18 · 18 commits · 239 Python tests + 9 JavaScript tests passing · ruff clean · 7 migrations applied to Neon._

Every row below was checked against the code, not against the last status note. Written against
the requirement IDs in [`../Riverbend-Ledger-PRD-Flask.md`](../Riverbend-Ledger-PRD-Flask.md).
[STATUS.md](STATUS.md) is the narrative companion to this table.

**Key:** ✅ done · 🟡 partly done · ⬜ not started

---

## 1. Build phases

| Phase | Scope | State | What is missing |
| --- | --- | --- | --- |
| 0 | Content pipeline: pack format, validation, zip import | 🟡 | The **generator** (workbook → zip) is not written; rule W1 |
| 1 | Data model, ledger engine, deployed skeleton | 🟡 | Engine and schema done; **nothing is deployed** |
| 2 | Journals and posting | 🟡 | Special-journal **column form**, live totals and the account picker |
| 3 | Documents and triage, both modes | ✅ | — |
| 4 | Trial balances, adjustments, statements, closing | 🟡 | Worksheet (cut list #1), row reordering, stage gating |
| 5 | Grading engine and storage | ✅ | — |
| 6 | Instructor console | 🟡 | Accommodations, checkpoint deadlines, roster import, exports beyond the cohort CSV |
| 7 | Multi-company | 🟡 | Schema and catalogue done; per-section availability and the student switcher are not |
| 8 | Accessibility pass, failure handling, deploy | ⬜ | None of it |

---

## 2. Student app (S1–S6)

| # | Requirement | State | Where / what is missing |
| --- | --- | --- | --- |
| S1.1 | Persistent navigation, company named and coloured | ✅ | `layouts/workspace.html` |
| S1.2 | Work saves as it is completed, no save button | ✅ | Entries on record; statements and worksheet cells on change |
| S1.3 | Leave and return on any device | ✅ | All state server-side |
| S1.4 | Progress indicator | 🟡 | Overview shows documents triaged; stage and journals posted only on the staff screen |
| S1.5 | Reference section (background, policies, chart, payroll) | ⬜ | The pack carries the blocks; no screen renders them |
| S2.1 | Screen mode: zoomable images, order received | ✅ | `pack_asset` + authorised route + `zoom.js` |
| S2.2 | Paper mode: references only | ✅ | Same queue, no image, route returns 404 |
| S2.3 | Record / No entry required | ✅ | |
| S2.4 | No-entry asks for a reason | ✅ | 1–200 characters, DB CHECK |
| S2.5 | A recorded document links to its entry | ✅ | |
| S2.6 | Dispositions can change until submission | ✅ | Supersession keeps the history |
| S2.7 | Documents cannot be deleted or hidden | ✅ | No such route |
| S2.8 | Alt text and a text alternative | ✅ | Shown to everyone, not as a fallback |
| S3.1 | Five journals | 🟡 | The engine, posting and the pack support all five; **recording uses the general-journal grid** |
| S3.2 | Special journals show their own columns | ⬜ | The column entry form is not built |
| S3.3 | The student chooses the journal | ✅ | |
| S3.4 | General Journal: any number of lines, live totals | 🟡 | Lines yes; **live totals need `entry-grid.js`** |
| S3.5 | Saving blocked out of balance, difference shown | ✅ | Validator + deferred DB trigger |
| S3.6 | Account picker searches number and name | 🟡 | Native `<select>`; the ARIA combobox is not built |
| S3.7 | Control-account lines need a party | ✅ | |
| S3.8 | Edit or void before posting; voids stay visible | ✅ | Revision snapshot before every edit |
| S3.9 | Keyboard-only entry | 🟡 | Forms are keyboard-usable; the shortcut map needs JavaScript |
| S3.10 | An entry is never lost | ✅ | `save.js`: retries on the same key, keeps a copy in the browser, survives an expired session |
| S4.1 | Posting is an explicit action | ✅ | |
| S4.2 | Special journals post column totals | ✅ | Derived at read time |
| S4.3 | Subsidiary posts per entry, and "post all" | ✅ | |
| S4.4 | Opening, December activity, closing balance | ✅ | Grouped regular / adjusting / closing |
| S4.5 | Ledger lines link back | ✅ | |
| S4.6 | Subsidiary total beside its control | ✅ | Says agrees or the difference |
| S4.7 | Posting can be reversed, logged | ✅ | |
| S5.1 | Trial balance generated, says only whether it balances | ✅ | Three stages |
| S5.2 | Adjusting entries flagged | ✅ | |
| S5.3 | Ten-column worksheet | ⬜ | Cut list #1 |
| S5.4 | Four statements | ✅ | Whatever statements the pack defines |
| S5.5 | The student builds them | ✅ | Rows, order and figures are theirs; subtotal types from the pack |
| S5.6 | The student closes the books | ✅ | No "close the year" button |
| S5.7 | Nothing says whether a statement is right | ✅ | A7 guard |
| S6.1 | Checkpoints: one figure, three attempts, lock | ✅ | |
| S6.2 | A locked checkpoint shows nothing else | ✅ | |
| S6.3 | Stages gated behind a checkpoint | ⬜ | Needs `assignment_checkpoint` |
| S6.4 | Submission checklist | ✅ | Documents, entries, statements started |
| S6.5 | Read-only after submission; instructor can reopen | 🟡 | Read-only yes; **no reopen screen** |
| S6.6 | Marks and comment after release | ✅ | `/marks` |
| S6.7 | Late policy | ✅ | Closed or accept-late with a cut-off |

---

## 3. Instructor console (I1–I5)

| # | Requirement | State | Where / what is missing |
| --- | --- | --- | --- |
| I1.1 | Create an assignment: company, paper or screen | ✅ | `/staff/assignments/new` |
| I1.2 | Due date and checkpoint deadlines | 🟡 | Dates yes; **checkpoint deadlines not** |
| I1.3 | Variant policy: in turn, random, manual | 🟡 | In turn and random work; manual leaves no way to assign by hand |
| I1.4 | Join code | ✅ | Generated, shown, rotatable |
| I1.5 | Roster CSV import | ⬜ | |
| I1.6 | Clone with new dates | ✅ | One field, one button |
| I1.7 | Upload a pack, validated first | ✅ | Zip, every problem reported at once |
| I1.8 | Enable / disable / archive per section | ⬜ | Needs `section_pack_availability` |
| I1.9 | Choose companies for a student-choice assignment | ⬜ | |
| I1.10 | Catalogue view | ✅ | Versions, period, scope, workspaces per version |
| I1.11 | Per-student accommodations | ⬜ | Table designed, not built |
| I1.12 | Clear or archive a workspace | ⬜ | |
| I1.13 | Late policy per assignment | ✅ | |
| I2.1 | One row per student: stage, documents, journals, activity | ✅ | Six bulk queries |
| I2.2 | Flag who has not started near the due date | ✅ | |
| I2.3 | Flag checkpoint lockouts with the figures | ✅ | |
| I2.4 | Open a workspace read-only | ✅ | Banner names the student |
| I2.5 | Last attempted save, including refused ones | ✅ | `activity.record_refused_save` |
| I2.6 | Issue a one-time sign-in code | ⬜ | Waits on real auth |
| I3.1 | Score automatically, method-not-match | ✅ | Ten components |
| I3.2 | Show what the rule credited | ✅ | Evidence per item |
| I3.3 | Flag what the engine cannot decide | ✅ | Review queue is a filter |
| I3.4 | Override with a reason | ✅ | Survives a regrade (A12) |
| I3.5 | Comment per student | ✅ | |
| I3.6 | Release marks in one action | ✅ | |
| I3.7 | Batched grading | ✅ | Ten per request |
| I3.8 | Unsubmitted graded as "Not submitted" | ✅ | Recorded on each run |
| I4.1 | Designed errors across the cohort | ✅ | Found and possible, counted apart |
| I4.2 | Documents handled differently from the key | ✅ | In both directions, plus not handled |
| I4.3 | Median time on task and its spread | ✅ | Breaks over 20 minutes count for nothing |
| I4.4 | Where students abandoned | ⬜ | PRD *Should* |
| I4.5 | Cohort CSV export | ✅ | Stable header |
| I4.6 | Compare a cohort across two companies | ⬜ | PRD *Should* |
| I5.1 | Marks CSV for an LMS | ⬜ | The cohort CSV is not the gradebook shape |
| I5.2 | One student's work as PDF | ⬜ | Print route not built |
| I5.3 | Answer key as PDF | ⬜ | |

---

## 4. Multiple companies (M1–M3)

| # | Requirement | State | Notes |
| --- | --- | --- | --- |
| M1.1 | Many packs at once | ✅ | |
| M1.2 | Each pack carries its own everything | ✅ | |
| M1.3 | Packs uploaded, nothing authored in the app | ✅ | |
| M1.4 | Enable / disable / archive per section | ⬜ | |
| M1.5 | Versions pinned by the workspace | ✅ | Composite FKs |
| M1.6 | Scope tags | ✅ | Shown in the catalogue |
| M2.1 | One company per workspace | ✅ | |
| M2.2 | Several assignments at once | ✅ | |
| M2.3 | Fixed or student-chosen company | 🟡 | Fixed works; choice is modelled, no screen |
| M2.4 | Choice locked after the first entry | ⬜ | |
| M2.5 | Prerequisite assignment | 🟡 | Column exists, nothing enforces it |
| M3.1 | Company in the chrome everywhere | ✅ | |
| M3.2 | Accent colour and mark | ✅ | Nonce'd style block |
| M3.3 | Company in the URL | ✅ | |
| M3.4 | Switching is explicit | ⬜ | Mismatch page exists; **no switcher** |
| M3.5 | Entry forms name the company | ✅ | |
| M3.6 | A reference from another company is named | ⬜ | Needs the document picker |
| M3.7 | Home lists assignments with company and progress | 🟡 | Company and status; no progress or deadline |

---

## 5. Acceptance criteria

| # | Criterion | State | Evidence |
| --- | --- | --- | --- |
| A1 | A student completes the cycle unaided | 🟡 | Every step exists; no pilot has run |
| A2 | Replaying the key matches to the cent | ✅ | DB replay + pure V9 |
| A3 | That replay scores full marks | ✅ | Pure **and** through the database |
| A4 | Out-of-balance cannot be saved | ✅ | Validator + trigger |
| A5 | Designed errors save with no warning | 🟡 | Signatures tested; no per-error save test |
| A6 | A trial balance on those errors reads "In balance" | ✅ | |
| A7 | No banned words in the student interface | 🟡 | Rendered screens checked; no full sweep |
| A8 | No key value reaches a student | 🟡 | Checkpoints proven; no full leak sweep |
| A9 | One early mistake still scores ≥ 85% | ✅ | 88.3%, pure and through the database |
| A10 | Each designed error named | 🟡 | Per detect type, not per signature |
| A11 | 40 students graded in under 30 s | ⬜ | No timing test |
| A12 | An override survives a regrade | ✅ | |
| A13 | Section, assignment, code, enrolled student | 🟡 | Tested end to end; timing unobserved |
| A14 | Cloning takes under a minute | 🟡 | One field; timing unobserved |
| A15 | A regenerated pack uploads unedited | 🟡 | Zips upload; the generator does not exist |
| A16 | Marks CSV imports into an LMS | ⬜ | |
| A17 | Every workflow by keyboard alone | 🟡 | Server-rendered forms are; unverified with a screen reader |
| A18 | Killing the server loses no saved work | 🟡 | The protocol is tested both sides; the browser itself needs Playwright |
| A19 | A2 for every company in the catalogue | 🟡 | One real company exists |
| A20 | Companies cannot reach each other | 🟡 | Composite FK + 404 proven; no two-pack test |
| A21 | No account-number literals in code | ⬜ | No lint rule |
| A22 | Disabling a company leaves work usable | ⬜ | Needs availability |
| A23 | Two charts with account 101 coexist | 🟡 | Scoping in place; no dedicated test |
| A24 | A student can tell which company, in 2 s | 🟡 | Chrome, colour, URL; unobserved |
| A25 | Sign-in survives the real world | ⬜ | Auth not built |
| A26 | No lost work | 🟡 | Contract and decisions tested; browser behaviour needs Playwright |
| A27 | Recovery proven | ⬜ | No backup script or drill |
| A28 | Late policy holds | ✅ | |
| A29 | Built CSS matches a fresh build | 🟡 | Committed; no CI check |
| A30 | The largest pack uploads in time | ⬜ | |

---

## 6. Technical pieces

| Piece | State | Notes |
| --- | --- | --- |
| Ledger engine (pure) | ✅ | Posting derivation, balances, trial balances, subsidiary proof |
| Grading engine (pure) | ✅ | Ten components, signatures, evidence, review flags |
| Grade storage | ✅ | Immutable runs, overrides, comments |
| Write path (lock, gates, one commit) | ✅ | |
| Composite scoping keys, balance trigger | ✅ | Proven against real Postgres |
| Pack schema, validation, zip import | ✅ | W1 outstanding |
| Document images | ✅ | In Postgres, behind an authorised route |
| Tailwind build, committed CSS | ✅ | No Node at deploy time |
| **CityReady design system** | ✅ | Navy chrome, teal actions, amber states; DM Serif Display / Outfit / JetBrains Mono, self-hosted; named component classes (`.panel`, `.data-table`, `.btn`, `.field`, `.callout`, `.nav-link`) rather than repeated utility strings |
| Contrast | ✅ | Every text pairing holds 4.5:1; teal carries text only in its deeper shade (5.16:1) |
| `zoom.js` | ✅ | The only JavaScript so far |
| `save.js` | ✅ | The no-loss protocol, with its decisions under `node --test` |
| `entry-grid.js`, `picker.js`, `batch.js` | ⬜ | S3.4, S3.6 and batched grading wait on these |
| Auth: magic link, codes, rate limits, Resend | ⬜ | **Dev-only sign-in**, refused in production |
| CLI commands (`staff add`, `packs`, `grade`, `purge`…) | ⬜ | |
| Heroku config: Procfile, gunicorn, release phase | ⬜ | |
| CI workflow | ⬜ | |
| Backups, restore drill, runbook | ⬜ | |
| Accessibility pass with a screen reader | ⬜ | Semantic tables and labels are in place |

---

## 7. Pack validation rules

| Rule | Checks | State | Runs in |
| --- | --- | --- | --- |
| V1–V4 | Schema, uniqueness, references, statement vocabulary | ✅ | `validate` |
| V5 | Required roles and one control account per party kind | ✅ | `validate` |
| V6, V7 | Opening balances balance; party totals tie to their control | ✅ | `validate` |
| V8 | Expected entries balance and fit their journal's columns | ✅ | `validate` |
| V9 | The key replays to its own expected balances (A2 at upload) | ✅ | `validate` |
| V10 | Checkpoints answered; every document triaged; ≤2 guided | ✅ | `validate` |
| V11 | Signatures the key would trigger; adjustment shapes | ✅ | `validate` |
| V12 | An image per variant, a real PNG ≤2 MB, alt text | ✅ | `importing` |
| V13 | Accent contrast, monogram | ✅ | `validate` |
| V14 | Newer version; archive not seen before | ✅ | `importing` |
| V15 | Rubric components known, points positive | ✅ | `validate` |
| V16 | Zip safety: paths, entries, unpacked size | ✅ | `zip_reader` |
| W1 | Warn on pack text using the four banned words | ⬜ | — |

---

## 8. Data model

| Built (29 tables) | Not built |
| --- | --- |
| `user`, `section`, `enrollment`, `staff_action` | `login_token` (waits on auth) |
| `content_pack`, `pack_version`, `variant`, `account`, `party`, `source_document`, `answer_key`, `account_opening_balance`, `party_opening_balance`, `pack_asset` | — |
| `assignment`, `workspace`, `disposition`, `journal_entry`, `journal_entry_revision`, `entry_line`, `posting_run`, `posting_run_entry` | `assignment_choice`, `assignment_checkpoint`, `assignment_override`, `section_pack_availability` |
| `statement_draft`, `statement_line`, `checkpoint_attempt`, `activity_event` | `worksheet_cell`, `checkpoint_grant` |
| `grade_run`, `grade_override`, `grade_comment` | — |

---

## 9. Tests (228)

| Area | Count | Covers |
| --- | --: | --- |
| Money, forms, web rendering | 55 | Integer cents, entry and statement parsing, template rendering with a partial A7 sweep |
| Ledger engine and replay | 9 | Posting derivation, balances, trial balances, the pure A2 |
| Packs: schema, rules, zip | 27 | V1–V11, V13, V15, and the zip safety rules |
| Grading engine | 26 | Ten components, signatures, time on task |
| Golden | 7 | A3 and A9, each pure **and** through the database |
| Guards | 6 | Import boundaries, route decoration, no inline styles or handlers, the JavaScript tests, no banned word in a script |
| Save protocol | 9 | Where to go next, when it saved, the version, idempotent retries, refusals, closed books, expired sessions |
| JavaScript (`node --test`) | 9 | What save.js decides: navigate, replace, retry, sign in, give up, and the backoff |
| Integration (live Neon) | 100 | Constraints, write path, dispositions, checkpoints, submission, statements, grading, storage, marks, progress, console, diagnostics, setup, uploads, images |

---

## 10. What I would do next, in order

1. **Auth** — magic link, six-digit codes, Resend. Nothing can leave a laptop without it.
3. **Deploy and CI** — Procfile, release phase, the workflow that runs these tests on every push.
4. **The generator** — workbook to pack zip. Until it exists, every pack is hand-written.
5. The console's remaining items: accommodations, checkpoint deadlines, roster import, marks CSV.
