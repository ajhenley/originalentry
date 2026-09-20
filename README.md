# Original Entry

A browser-based accounting system simulation for **Principles of Financial Accounting** — the
Flask build of *Riverbend Ledger*.

Students work the full December accounting cycle for a fictional company: triage source documents,
journalise into special and general journals, post to general and subsidiary ledgers, adjust, build
financial statements, and close the books. Ledgers and trial balances are **derived** from posted
entries, never stored, so nothing can be mis-transcribed. The interesting lesson — *"it balances but
it is wrong"* — is preserved.

This repository is **private**: content packs include answer keys.

See [`../Riverbend-Ledger-PRD-Flask.md`](../Riverbend-Ledger-PRD-Flask.md) for the full technical
requirements and [`../Riverbend-Ledger-PRD.md`](../Riverbend-Ledger-PRD.md) for the product PRD.

## Stack

Python 3.13 · Flask 3.1 (app factory, `auth`/`student`/`staff` blueprints) · Jinja + Tailwind v4
(standalone CLI, built CSS committed) · SQLAlchemy 2.0 + Flask-Migrate · Neon Postgres 18 (psycopg 3)
· Flask-Login magic-link + six-digit-code auth · Resend for sign-in email only · Heroku hosting.

## Build order (PRD §7)

The engine is built and tested **before any screen**. The pure `originalentry/ledger/` engine reproduces
the answer key's balances to the cent (**A2**) with no database and no Flask. That is the first thing
that must be true.

| Phase | Scope | Status |
| --- | --- | --- |
| 0 | Pack schema + validation, generator, TestCo packs | in progress |
| 1 | Deployed skeleton + pure ledger engine (A2 engine-only) | **in progress** |
| 2 | Journals, entry/posting, `save.js`, pickers | pending |
| 3 | Documents, dispositions, images, workspace chrome | pending |
| 4 | Trial balances, adjustments, statements, closing, checkpoints | pending |
| 5 | Grading engine (10 components, signatures, batching) | pending |
| 6 | Staff console | pending |
| 7 | Multi-company (catalogue, availability, migration) | pending |
| 8 | Hardening, a11y, backups, runbook | pending |

## What exists so far

- `originalentry/money.py` — integer-cent parsing and formatting. Money is **integer cents everywhere**;
  never a float (D6 rule 1).
- `originalentry/messages.py` — every student-facing string. No "correct/incorrect/right/wrong" (A7).
- `originalentry/ledger/` — the **pure** engine (stdlib + `money` only): dataclass snapshot types,
  posting derivation, balances, trial balances, and the subsidiary proof.
- `originalentry/packs/schema.py` — pydantic schema for `pack.json` and answer keys, shared by the app
  and the offline generator so the two cannot disagree about the format.

## Developing

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest                 # pure engine + money + schema tests need no database
pytest -m "not db"     # explicitly skip database-backed tests
```

The ledger engine and its tests deliberately import **no Flask and no SQLAlchemy** — a guard test
enforces that boundary (T3.1).

## Deploy (Heroku, T13)

Stack `heroku-24`, buildpack `heroku/python`; Python from `.python-version`. Processes come from
the `Procfile`: `web` runs gunicorn (`gunicorn.conf.py` — 2 workers × 4 threads, 25 s timeout),
and the `release` phase runs `flask db upgrade` through the **direct** Neon endpoint.

Config vars (T13): `SECRET_KEY`, `DATABASE_URL` (pooled), `DATABASE_URL_DIRECT` (direct),
`APP_ENV=production`, `APP_BASE_URL` (`https://originalentry.com`), `COURSE_TZ`,
`EMAIL_BACKEND=resend`, `RESEND_API_KEY`,
`MAIL_FROM`, `MAIL_REPLY_TO`, `WEB_CONCURRENCY`. Do **not** attach a Heroku Postgres add-on (it
would overwrite `DATABASE_URL`). The built CSS is committed, so the Heroku build has no CSS step.

```bash
git push heroku main          # release phase migrates, then the web dyno boots
heroku run "ORIGINALENTRY_USE_DIRECT_DB=1 flask staff add you@example.edu --role instructor"
```

## Continuous integration (T14.1)

`.github/workflows/ci.yml` runs on push/PR against a `postgres:17` service, **serially** (the DB
suite shares fixture slugs and would collide with a parallel run): ruff → rebuild the CSS and fail
on any difference (A29) → apply every migration to an empty database → run the whole test suite
(unit, integration, golden, guards, and the node JavaScript tests).

## Backups (OPS-2)

`scripts/backup.sh [OUT_DIR]` runs `pg_dump` (custom format) through the **direct** Neon endpoint;
run it the day before each due date and at term end, to an encrypted disk.

```bash
DATABASE_URL_DIRECT="postgresql+psycopg://…direct-host…/neondb?sslmode=require" \
  scripts/backup.sh ~/originalentry-backups
# restore:
pg_restore --clean --no-owner --no-privileges \
  --dbname "postgresql://…direct-host…/neondb?sslmode=require" originalentry-YYYYMMDD-HHMMSS.dump
```

The client tools must be at least as new as the server: Neon upgrades Postgres without asking,
and `pg_dump` refuses a newer server. `backup.sh` checks this and names the package to install.

Once a term, run the drill: restore into a throwaway Neon branch, run `flask replay-key`, delete
the branch. Neon point-in-time restore (≥ 7 days) is the first line; this dump is the offline copy.

## Due-date evening runbook (OPS-3)

Before the deadline evening, and once during it:

1. **Uptime monitor** — `/healthz` green for the last hour.
2. **Heroku** — response times, dyno memory (Basic is 512 MB), and the H12 (request timeout) count.
   A rising H12 count means a slow query or a cold Neon compute.
3. **Neon** — the compute graph; autosuspend should be **off** on `main` during term so the first
   request of the evening is not slow.
4. **Resend** — the dashboard for bounces and the daily send count (a paid plan removes the cap).
   If sign-in email is failing, issue codes with `flask auth issue-link` or the staff code screen.
5. **Progress screen** — scan each section for checkpoint lockouts and "not started" flags.
6. If the app is unavailable for more than 30 minutes within 24 h of a deadline, extend the
   deadline by 24 h (OPS-6): change the assignment's due date.

Hotfix window (OPS-5): within 48 h of a due date, deploy only a fix for a problem students are
hitting, only if there is no migration, CI is green, `replay-key` passes on staging, and the
rollback command (`heroku releases:rollback`) is ready. Otherwise extend the deadline.
