# Original Docket — deadline engine implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the pure deadline-computation engine for Original Docket — given a trigger date,
a rule, and how a document was served, produce the due date together with the working that
justifies it.

**Architecture:** A new package `originalentry/docket/` beside `ledger/` and `grading/`, holding
frozen dataclasses and one function. No Flask, no SQLAlchemy, no ORM models, no database. It is
exhaustively testable without a database, which is the point: date arithmetic is where the bugs
will be, and this is the phase that proves the derivation model survives contact with the rules.

**Tech Stack:** Python 3.13+, stdlib `datetime` only, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-23-paralegal-case-file-design.md`

## Global Constraints

- **Python ≥ 3.13**, ruff line-length 100, lint rules `E, F, I, UP, B` (`pyproject.toml`).
- **The package must stay pure.** No import of `flask`, `sqlalchemy`, `psycopg`,
  `originalentry.models`, or `originalentry.grading`. Task 1 adds the guard that enforces this.
- **Every module opens with a docstring** naming the rule it implements, following
  `originalentry/ledger/models.py`.
- **`from __future__ import annotations`** at the top of every module.
- **No new runtime dependencies.** `requirements.txt` is unchanged by this phase.
- **Dates are `datetime.date`.** Never strings, never datetimes.
- This phase adds **no database tables, no routes, no templates**.

## A deliberate omission, and why

The spec's pack format says a rule declares whether its days are "calendar or business". **This
plan implements calendar days only.**

Since the 2009 amendments, FRCP 6(a)(1)(B) counts *every* day, "including intermediate
Saturdays, Sundays, and legal holidays". The old regime, where periods under eleven days
excluded weekends, was abolished. Since the spec's non-goals restrict v1 to the federal rules,
a business-day code path would have no caller.

**Action for the spec owner:** amend §7 of the spec to drop `calendar or business` from the rule
format, or record why it stays. Do not implement it speculatively.

## File structure

| File | Responsibility |
| --- | --- |
| `originalentry/docket/__init__.py` | Package marker. Empty. |
| `originalentry/docket/models.py` | `Rule`, `Calendar`, `Step`, `Derivation`, service-method constants. Data only, no logic beyond `Calendar.is_closed`. |
| `originalentry/docket/engine.py` | `compute()`. The only function that knows the counting rules. |
| `tests/unit/test_docket_engine.py` | Everything about counting, rolling, extending, and the error catalogue. |
| `tests/guards/test_import_boundaries.py` | **Modify** — extend the existing purity guard to cover `docket/`. |

All test dates fall in **2026**, whose federal holidays are fixed in the test module. Every
expected date in this plan was computed and verified before being written down.

---

### Task 1: The package, its dataclasses, and the purity guard

**Files:**
- Create: `originalentry/docket/__init__.py`, `originalentry/docket/models.py`
- Modify: `tests/guards/test_import_boundaries.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Rule(key, label, days, extension_days=3)`; `Calendar(holidays: frozenset[date])`
  with `is_closed(day) -> bool`; `Step(rule, says, lands_on)`; `Derivation(due, steps)`;
  constants `PERSONAL`, `ELECTRONIC`, `MAIL`, `LEFT_WITH_CLERK`, `CONSENTED_OTHER`, and
  `EXTENDING_METHODS: frozenset[str]`.

- [ ] **Step 1: Rewrite the purity guard to cover both engines**

Replace the whole of `tests/guards/test_import_boundaries.py` with:

```python
"""Module-boundary guard (T3.1): a pure engine must not import Flask, SQLAlchemy, the ORM
models, or grading. ``ledger/snapshot.py`` is the sole allowed door to the database and is
exempt. ``docket/`` has no such door: it never touches the database at all."""

import ast
import pathlib

import pytest

ENGINES = pathlib.Path(__file__).resolve().parents[2] / "originalentry"
FORBIDDEN_TOP = {"flask", "sqlalchemy", "psycopg"}
FORBIDDEN_INTERNAL = {"originalentry.models", "originalentry.grading"}
EXEMPT = {"snapshot.py"}


def _imported_modules(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            mods.add(node.module)
    return mods


@pytest.mark.parametrize("package", ["ledger", "docket"])
def test_the_engine_stays_pure(package):
    offenders: list[str] = []
    for path in (ENGINES / package).glob("*.py"):
        if path.name in EXEMPT:
            continue
        for mod in _imported_modules(path):
            top = mod.split(".")[0]
            if top in FORBIDDEN_TOP or mod in FORBIDDEN_INTERNAL:
                offenders.append(f"{path.name} imports {mod}")
    assert not offenders, (
        f"{package}/ must import only stdlib + originalentry.money: " + "; ".join(offenders)
    )
```

- [ ] **Step 2: Run it and watch the new case fail**

Run: `.venv/bin/python -m pytest tests/guards/test_import_boundaries.py -v`
Expected: `test_the_engine_stays_pure[ledger]` PASSES,
`test_the_engine_stays_pure[docket]` FAILS — the glob finds no directory, so the test errors on
a missing path. That failure is the point: the guard is watching a package that does not exist
yet.

- [ ] **Step 3: Create the package and its dataclasses**

Create `originalentry/docket/__init__.py` as an empty file.

Create `originalentry/docket/models.py`:

```python
"""Pure dataclasses for the docket engine.

These are the engine's only view of the world. They carry no database identity and no Flask.
A rule is what the student's booklet prints; a calendar is the days the court is shut; a
derivation is the working that justifies a date, which is the thing this engine exists to
produce. See FRCP 6(a) and 6(d).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

# How a document was served.
PERSONAL = "personal"
ELECTRONIC = "electronic"
MAIL = "mail"
LEFT_WITH_CLERK = "clerk"
CONSENTED_OTHER = "other"

# The methods that add days under Rule 6(d), being service under Rule 5(b)(2)(C), (D) and (F).
# Personal service and service through the court's electronic system do not extend a period.
EXTENDING_METHODS = frozenset({MAIL, LEFT_WITH_CLERK, CONSENTED_OTHER})


@dataclass(frozen=True)
class Rule:
    """One rule as the student's booklet prints it.

    ``days`` is always a count of calendar days: since 2009 FRCP 6(a)(1)(B) counts every day,
    including intermediate weekends and holidays.
    """

    key: str
    label: str
    days: int
    extension_days: int = 3


@dataclass(frozen=True)
class Calendar:
    """The days this court is shut, beyond the weekend."""

    holidays: frozenset[date] = frozenset()

    def is_closed(self, day: date) -> bool:
        return day.weekday() >= 5 or day in self.holidays


@dataclass(frozen=True)
class Step:
    """One move in the working, so that a wrong answer can be told from a wrong method."""

    rule: str
    says: str
    lands_on: date | None


@dataclass(frozen=True)
class Derivation:
    """A date and the working that justifies it."""

    due: date
    steps: tuple[Step, ...]
```

- [ ] **Step 4: Run the guard again**

Run: `.venv/bin/python -m pytest tests/guards/test_import_boundaries.py -v`
Expected: both parameters PASS.

- [ ] **Step 5: Commit**

```bash
git add originalentry/docket tests/guards/test_import_boundaries.py
git commit -m "Add the docket engine's dataclasses, and guard its purity

A deadline is not a number: it is a date and the working that justifies it. Derivation carries
both, so that a student who applied the right rule and slipped a day can be told apart from one
who applied the wrong rule and arrived somewhere plausible.

The purity guard now covers both engines rather than only the ledger."
```

---

### Task 2: Count the period

**Files:**
- Create: `originalentry/docket/engine.py`, `tests/unit/test_docket_engine.py`

**Interfaces:**
- Consumes: `Rule`, `Calendar`, `Step`, `Derivation` from Task 1.
- Produces: `compute(trigger: date, rule: Rule, service_method: str, calendar: Calendar) ->
  Derivation`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_docket_engine.py`:

```python
"""Computing a deadline under FRCP 6(a) and 6(d).

Every expected date here was worked by hand against the 2026 calendar before it was written
down. Where a test names a weekday, that weekday is part of the assertion: a rule that rolled
a date onto a Saturday would still produce a plausible-looking answer.
"""

from datetime import date

import pytest
from originalentry.docket.engine import compute
from originalentry.docket.models import PERSONAL, Calendar, Rule

# United States federal holidays in 2026, as observed.
HOLIDAYS_2026 = frozenset({
    date(2026, 1, 1),    # New Year's Day
    date(2026, 1, 19),   # Birthday of Martin Luther King, Jr.
    date(2026, 2, 16),   # Washington's Birthday
    date(2026, 5, 25),   # Memorial Day
    date(2026, 6, 19),   # Juneteenth
    date(2026, 7, 3),    # Independence Day, observed
    date(2026, 9, 7),    # Labor Day
    date(2026, 10, 12),  # Columbus Day
    date(2026, 11, 11),  # Veterans Day
    date(2026, 11, 26),  # Thanksgiving
    date(2026, 12, 25),  # Christmas Day
})

COURT = Calendar(holidays=HOLIDAYS_2026)

# FRCP 12(a)(1)(A)(i): a defendant must serve an answer within 21 days after being served.
ANSWER = Rule(key="frcp-12-a-1-A-i", label="Answer to a complaint", days=21)


def test_the_day_of_service_is_not_counted():
    """FRCP 6(a)(1)(A): exclude the day of the event that triggers the period. A complaint
    served on Monday 2 March is answerable on Monday 23 March, not Sunday 22 March."""
    result = compute(date(2026, 3, 2), ANSWER, PERSONAL, COURT)

    assert result.due == date(2026, 3, 23)
```

- [ ] **Step 2: Run it to watch it fail**

Run: `.venv/bin/python -m pytest tests/unit/test_docket_engine.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'originalentry.docket.engine'`.

- [ ] **Step 3: Write the minimal implementation**

Create `originalentry/docket/engine.py`:

```python
"""Computing a deadline from a document, under FRCP 6(a) and 6(d).

The engine returns the working, not just the answer. Three things need it: the answer key is
generated from it, the marking explains where a student diverged, and the instructor's solution
shows how the date was reached rather than asserting it.
"""

from __future__ import annotations

from datetime import date, timedelta

from .models import Calendar, Derivation, Rule, Step


def compute(trigger: date, rule: Rule, service_method: str, calendar: Calendar) -> Derivation:
    steps: list[Step] = [
        Step("FRCP 6(a)(1)(A)", f"Exclude the day of service, {trigger:%-d %B %Y}.", trigger),
    ]

    landed = trigger + timedelta(days=rule.days)
    steps.append(Step(
        "FRCP 6(a)(1)(B)",
        f"Count {rule.days} days, including weekends and holidays.",
        landed,
    ))

    return Derivation(due=landed, steps=tuple(steps))
```

- [ ] **Step 4: Run the test to watch it pass**

Run: `.venv/bin/python -m pytest tests/unit/test_docket_engine.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add originalentry/docket/engine.py tests/unit/test_docket_engine.py
git commit -m "Count the period, excluding the day of service

FRCP 6(a)(1)(A) and (B). The day of the triggering event is excluded and every day after it is
counted, weekends and holidays included, which has been the rule since the 2009 amendments
abolished the separate treatment of periods under eleven days."
```

---

### Task 3: Roll off a day the court is shut

**Files:**
- Modify: `originalentry/docket/engine.py`, `tests/unit/test_docket_engine.py`

**Interfaces:**
- Consumes: `compute()` from Task 2.
- Produces: no signature change. `Derivation.steps` gains a third `Step` when a roll happens.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_docket_engine.py`:

```python
def test_a_period_ending_on_a_saturday_runs_to_monday():
    """FRCP 6(a)(1)(C). Served Saturday 7 March, the twenty-first day is Saturday 28 March,
    so the answer is due Monday 30 March."""
    result = compute(date(2026, 3, 7), ANSWER, PERSONAL, COURT)

    assert result.due == date(2026, 3, 30)
    assert result.due.weekday() == 0


def test_a_period_ending_on_a_court_holiday_runs_to_the_next_open_day():
    """Served Monday 26 January, the twenty-first day is Monday 16 February, which is
    Washington's Birthday, so the answer is due Tuesday 17 February."""
    result = compute(date(2026, 1, 26), ANSWER, PERSONAL, COURT)

    assert result.due == date(2026, 2, 17)


def test_a_period_ending_on_an_open_day_is_left_alone():
    result = compute(date(2026, 3, 2), ANSWER, PERSONAL, COURT)

    assert result.due == date(2026, 3, 23)
    assert not any("6(a)(1)(C)" in step.rule for step in result.steps)


def test_the_working_names_the_rule_that_moved_the_date():
    result = compute(date(2026, 3, 7), ANSWER, PERSONAL, COURT)

    moved = [s for s in result.steps if s.rule == "FRCP 6(a)(1)(C)"]
    assert len(moved) == 1
    assert moved[0].lands_on == date(2026, 3, 30)
```

- [ ] **Step 2: Run them to watch them fail**

Run: `.venv/bin/python -m pytest tests/unit/test_docket_engine.py -v`
Expected: the three new roll tests FAIL with dates two days early
(`assert date(2026, 3, 28) == date(2026, 3, 30)`).
`test_a_period_ending_on_an_open_day_is_left_alone` PASSES already — that is correct and
expected, since it guards against over-rolling.

- [ ] **Step 3: Implement the roll**

In `originalentry/docket/engine.py`, add this helper above `compute`:

```python
def _roll(landed: date, calendar: Calendar, steps: list[Step]) -> date:
    """FRCP 6(a)(1)(C): if the last day is a weekend or a legal holiday, the period runs to
    the end of the next day that is neither."""
    if not calendar.is_closed(landed):
        return landed
    moved = landed
    while calendar.is_closed(moved):
        moved += timedelta(days=1)
    steps.append(Step(
        "FRCP 6(a)(1)(C)",
        f"{landed:%A %-d %B} is not a day the court is open, so the period runs on.",
        moved,
    ))
    return moved
```

Then in `compute`, replace the `return` with:

```python
    landed = _roll(landed, calendar, steps)

    return Derivation(due=landed, steps=tuple(steps))
```

- [ ] **Step 4: Run the tests to watch them pass**

Run: `.venv/bin/python -m pytest tests/unit/test_docket_engine.py -v`
Expected: all five PASS.

- [ ] **Step 5: Commit**

```bash
git add originalentry/docket/engine.py tests/unit/test_docket_engine.py
git commit -m "Run a period on when it ends on a day the court is shut

FRCP 6(a)(1)(C). A deadline that lands on a Saturday or Washington's Birthday is not a deadline,
and a student who leaves it there has produced a date that looks entirely ordinary."
```

---

### Task 4: Add three days for service by mail, after the roll and not before

**Files:**
- Modify: `originalentry/docket/engine.py`, `tests/unit/test_docket_engine.py`

**Interfaces:**
- Consumes: `compute()`, `_roll()` from Task 3.
- Produces: no signature change. `Derivation.steps` gains a `FRCP 6(d)` step when the method
  extends.

- [ ] **Step 1: Write the failing tests**

Widen the import at the top of `tests/unit/test_docket_engine.py` — `ruff` selects `F`, so an
import added before the test that uses it fails `F401`:

```python
from originalentry.docket.models import ELECTRONIC, MAIL, PERSONAL, Calendar, Rule
```

Then append to `tests/unit/test_docket_engine.py`:

```python
INTERROGATORIES = Rule(key="frcp-33-b-2", label="Answers to interrogatories", days=30)


def test_service_by_mail_adds_three_days():
    """FRCP 6(d). Interrogatories served Monday 4 May run to Wednesday 3 June, and three days
    for the post make Monday 8 June."""
    result = compute(date(2026, 5, 4), INTERROGATORIES, MAIL, COURT)

    assert result.due == date(2026, 6, 8)


def test_personal_service_adds_nothing():
    result = compute(date(2026, 5, 4), INTERROGATORIES, PERSONAL, COURT)

    assert result.due == date(2026, 6, 3)


def test_electronic_service_adds_nothing():
    """Service through the court's system is not within Rule 5(b)(2)(C), (D) or (F)."""
    result = compute(date(2026, 5, 4), INTERROGATORIES, ELECTRONIC, COURT)

    assert result.due == date(2026, 6, 3)


def test_the_three_days_are_rolled_again_if_they_land_on_a_weekend():
    """Served Monday 5 January, thirty days is Wednesday 4 February, plus three is Saturday
    7 February, so the date runs on to Monday 9 February."""
    result = compute(date(2026, 1, 5), INTERROGATORIES, MAIL, COURT)

    assert result.due == date(2026, 2, 9)


def test_the_extension_is_applied_after_the_period_has_run_not_before():
    """The trap this ordering creates. A complaint served Saturday 3 January runs to Saturday
    24 January, which is rolled to Monday 26 January, and three days for the post make
    Thursday 29 January.

    Adding the three days first gives Tuesday 27 January: two days early, a weekday, and
    entirely plausible on its face."""
    result = compute(date(2026, 1, 3), ANSWER, MAIL, COURT)

    assert result.due == date(2026, 1, 29)
    assert result.due != date(2026, 1, 27)
```

- [ ] **Step 2: Run them to watch them fail**

Run: `.venv/bin/python -m pytest tests/unit/test_docket_engine.py -v`
Expected: the three mail tests FAIL (three days short).
`test_personal_service_adds_nothing` and `test_electronic_service_adds_nothing` PASS already —
correct, and they guard against extending a period that should not be extended.

- [ ] **Step 3: Implement the extension**

In `originalentry/docket/engine.py`, add `EXTENDING_METHODS` to the import from `.models`, then
insert before the final `return`:

```python
    if service_method in EXTENDING_METHODS and rule.extension_days:
        landed = landed + timedelta(days=rule.extension_days)
        steps.append(Step(
            "FRCP 6(d)",
            f"Service was by {service_method}, so add {rule.extension_days} days "
            f"after the period has run.",
            landed,
        ))
        landed = _roll(landed, calendar, steps)
```

- [ ] **Step 4: Run the tests to watch them pass**

Run: `.venv/bin/python -m pytest tests/unit/test_docket_engine.py -v`
Expected: all ten PASS.

- [ ] **Step 5: Commit**

```bash
git add originalentry/docket/engine.py tests/unit/test_docket_engine.py
git commit -m "Add the three days for the post, after the period has run

FRCP 6(d) adds three days when service was by mail, and it adds them *after* the period would
otherwise expire under 6(a) — which means after the roll, not before it.

Getting that order wrong moves the date by two days and leaves it on a weekday. A complaint
served on Saturday 3 January is answerable on Thursday 29 January; the wrong order gives Tuesday
the 27th, and nothing about the calendar says which is which."
```

---

### Task 5: A table of worked answers

**Files:**
- Modify: `tests/unit/test_docket_engine.py`

**Interfaces:**
- Consumes: `compute()` as completed in Task 4.
- Produces: nothing new. This task adds evidence, not code.

This is the analogue of `tests/unit/test_riverbend_pack.py`, which checks the app's figures
against the printed key. Here it pins whole scenarios so that a later change to the engine
cannot quietly move an answer.

- [ ] **Step 1: Write the table**

Append to `tests/unit/test_docket_engine.py`:

```python
REQUESTS = Rule(key="frcp-34-b-2-A", label="Responses to requests for production", days=30)

# Each row was worked by hand against the 2026 calendar: served, rule, method, due, and why.
WORKED = [
    (date(2026, 3, 2), ANSWER, PERSONAL, date(2026, 3, 23),
     "clean: the twenty-first day is a Monday"),
    (date(2026, 3, 6), ANSWER, PERSONAL, date(2026, 3, 27),
     "clean: the twenty-first day is a Friday"),
    (date(2026, 3, 7), ANSWER, PERSONAL, date(2026, 3, 30),
     "lands on a Saturday and runs to Monday"),
    (date(2026, 1, 26), ANSWER, PERSONAL, date(2026, 2, 17),
     "lands on Washington's Birthday and runs to Tuesday"),
    (date(2026, 3, 2), ANSWER, MAIL, date(2026, 3, 26),
     "clean, plus three days for the post"),
    (date(2026, 1, 3), ANSWER, MAIL, date(2026, 1, 29),
     "rolled off a Saturday, then three days for the post"),
    (date(2026, 5, 4), INTERROGATORIES, MAIL, date(2026, 6, 8),
     "thirty days, then three, landing on a Monday"),
    (date(2026, 1, 5), INTERROGATORIES, MAIL, date(2026, 2, 9),
     "the three days land on a Saturday and run to Monday"),
    (date(2026, 6, 1), REQUESTS, PERSONAL, date(2026, 7, 1),
     "thirty days, clean"),
    (date(2026, 6, 1), REQUESTS, MAIL, date(2026, 7, 6),
     "thirty days, then three across the Independence Day holiday"),
]


@pytest.mark.parametrize(("served", "rule", "method", "due", "why"), WORKED)
def test_the_worked_answers_still_hold(served, rule, method, due, why):
    assert compute(served, rule, method, COURT).due == due, why


def test_the_working_is_always_returned():
    """A date with no working behind it cannot be marked or explained."""
    for served, rule, method, _due, _why in WORKED:
        result = compute(served, rule, method, COURT)
        assert result.steps
        assert result.steps[-1].lands_on == result.due
```

- [ ] **Step 2: Run the table**

Run: `.venv/bin/python -m pytest tests/unit/test_docket_engine.py -v`
Expected: all rows PASS. If any fails, **do not adjust the table to match the code** — the table
was worked by hand and is the authority. Fix the engine.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_docket_engine.py
git commit -m "Pin ten worked answers against the 2026 calendar

Each row was computed by hand before it was written down, and covers one branch: a clean count,
a roll off a weekend, a roll off a holiday, the three days for the post, and the three days
themselves landing on a weekend.

The table is the authority. If the engine disagrees with it, the engine is wrong."
```

---

### Task 6: Prove the traps are traps

**Files:**
- Modify: `tests/unit/test_docket_engine.py`

**Interfaces:**
- Consumes: `compute()` as completed in Task 4.
- Produces: nothing new. This task proves a property of the design.

The spec rests on a claim: every common error produces a *plausible* date. If a wrong method
happened to give the right answer, that error could not be taught, and if it gave an obviously
absurd date, it would not need teaching. This task holds the claim to account.

- [ ] **Step 1: Write the error catalogue**

Append to `tests/unit/test_docket_engine.py`:

```python
# ── The traps ───────────────────────────────────────────────────────────────────────────
#
# The set is built on the claim that every common error still produces a date a student has no
# reason to doubt. These tests hold that claim to account: each wrong method must give a
# different answer from the right one, and must give a weekday.

def _wrong_counted_from_nothing_excluded(served, rule):
    """Counting the day of service as day one."""
    return served + timedelta(days=rule.days - 1)


def _wrong_no_extension(served, rule, calendar):
    """Forgetting that service by post adds three days."""
    return compute(served, rule, PERSONAL, calendar).due


def _wrong_extension_before_the_roll(served, rule, calendar):
    """Adding the three days before rolling off the weekend instead of after."""
    landed = served + timedelta(days=rule.days + rule.extension_days)
    while calendar.is_closed(landed):
        landed += timedelta(days=1)
    return landed


# The ordering only shows itself when the period first lands on a closed day: if it does not,
# rolling before or after the three days gives the same answer. Both dates below were chosen
# because the first roll fires. Served 3 January gives Thursday 29th against Tuesday the 27th;
# served 1 January gives Thursday 5 February against Tuesday the 3rd.
@pytest.mark.parametrize(("served", "rule", "wrong"), [
    (date(2026, 1, 3), ANSWER, _wrong_extension_before_the_roll),
    (date(2026, 1, 1), INTERROGATORIES, _wrong_extension_before_the_roll),
])
def test_mistiming_the_extension_gives_a_different_and_plausible_date(served, rule, wrong):
    right = compute(served, rule, MAIL, COURT).due
    slipped = wrong(served, rule, COURT)

    assert slipped != right, "this error would be invisible: it gives the right answer"
    assert not COURT.is_closed(slipped), "this error is self-announcing: it gives a closed day"


@pytest.mark.parametrize("served", [date(2026, 3, 2), date(2026, 5, 4), date(2026, 6, 1)])
def test_forgetting_the_post_gives_a_different_and_plausible_date(served):
    right = compute(served, INTERROGATORIES, MAIL, COURT).due
    slipped = _wrong_no_extension(served, INTERROGATORIES, COURT)

    assert slipped != right
    assert not COURT.is_closed(slipped)


@pytest.mark.parametrize("served", [date(2026, 3, 2), date(2026, 3, 6), date(2026, 5, 4)])
def test_counting_the_day_of_service_gives_a_different_date(served):
    right = compute(served, ANSWER, PERSONAL, COURT).due
    slipped = _wrong_counted_from_nothing_excluded(served, ANSWER)

    assert slipped != right
```

Add `timedelta` to the datetime import at the top of the test module:

```python
from datetime import date, timedelta
```

- [ ] **Step 2: Run the catalogue**

Run: `.venv/bin/python -m pytest tests/unit/test_docket_engine.py -v`
Expected: all PASS.

If `assert not COURT.is_closed(slipped)` fails for some date, that is a **finding, not a bug**:
it means that for that trigger date the error announces itself, and the pack author must not use
that date for that trap. Record it in the spec rather than weakening the test.

- [ ] **Step 3: Run the whole suite and the linter**

Run: `.venv/bin/python -m pytest tests/unit tests/guards -q`
Expected: all pass, no errors or warnings.

Run: `.venv/bin/python -m ruff check originalentry/docket tests/unit/test_docket_engine.py`
Expected: no findings.

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_docket_engine.py
git commit -m "Hold the traps to account

The set rests on a claim: every common error still produces a date a student has no reason to
doubt. An error that gave the right answer could not be taught, and one that gave an obviously
absurd date would not need teaching.

So each wrong method is computed alongside the right one and must differ from it, and must land
on a day the court is open. Where it does not, that is a finding about which dates a pack author
may use for that trap, not a reason to weaken the test."
```

---

## What this phase deliberately leaves out

- **No database, no tables, no routes, no templates.** `DeadlineEntry` and `IndexEntry` are
  phase 3.
- **No pack format and no validation rules.** Phase 2.
- **No index or chronology engine.** The index is a row comparison and carries none of the risk
  that the date arithmetic does; it belongs with the pack work in phase 2.
- **No business-day counting.** See the omission recorded above.

## Before phase 2 begins

**A paralegal instructor or attorney must confirm the rules.** Everything here is internally
consistent and tested, and internal consistency is exactly what a wrong reading of a rule would
also look like. The engine is built so that this review is possible: `Derivation.steps` names
the rule relied on at each move, so the reviewer reads the working rather than the code.

Specifically, confirm:

1. Rule 6(d)'s three days are added after the period expires under 6(a), and the result is then
   rolled again under 6(a)(1)(C) if it lands on a closed day.
2. Service through the court's electronic filing system does not extend a period.
3. All periods are counted in calendar days.
4. The 2026 federal holiday dates fixed in the test module, particularly Independence Day
   observed on Friday 3 July 2026.
