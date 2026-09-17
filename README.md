# Parchment

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
(standalone CLI, built CSS committed) · SQLAlchemy 2.0 + Flask-Migrate · Neon Postgres 17 (psycopg 3)
· Flask-Login magic-link + six-digit-code auth · Resend for sign-in email only · Heroku hosting.

## Build order (PRD §7)

The engine is built and tested **before any screen**. The pure `parchment/ledger/` engine reproduces
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

- `parchment/money.py` — integer-cent parsing and formatting. Money is **integer cents everywhere**;
  never a float (D6 rule 1).
- `parchment/messages.py` — every student-facing string. No "correct/incorrect/right/wrong" (A7).
- `parchment/ledger/` — the **pure** engine (stdlib + `money` only): dataclass snapshot types,
  posting derivation, balances, trial balances, and the subsidiary proof.
- `parchment/packs/schema.py` — pydantic schema for `pack.json` and answer keys, shared by the app
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

## Due-date evening runbook

_(OPS-3 — to be filled in during phase 8.)_ Check the uptime monitor, Heroku response times / memory
/ H12 count, the Neon compute graph, the Resend dashboard (bounces + daily count), and the Progress
screen for lockouts.
