# Ashgrove Millwork Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Author a manufacturing practice set — a small family-owned cabinet shop, sole
proprietorship — as the catalog's fourth paper case.

**Architecture:** One new data module, `practicesets/companies/ashgrove.py`, defining the same
42 names the three existing companies define. The generators are not modified: they read whichever
company `PRACTICESET_COMPANY` names and print it. Correctness is proved by the repository's own
verifiers — the trial balance must net to zero, every subsidiary ledger must tie to its control,
and every designed trap must leave the trial balance in balance — plus new tests for the cost-flow
invariants this case introduces.

**Tech Stack:** Python 3.14, `Decimal` arithmetic throughout, pytest. No new dependencies.

**Spec:** `originalentry/docs/superpowers/specs/2026-10-05-ashgrove-millwork-design.md`

**Repository:** All work happens in `practicesets`, which is a **separate git repository** from
`originalentry` (where this plan and the spec live). Branch there, commit there.

---

## Prerequisite: the test suite cannot currently run

`tests/test_topdf_names.py` fails at collection. Homebrew's `python@3.14` ships a `pyexpat`
linked against a `/usr/lib/libexpat.1.dylib` that does not satisfy it:

```
ImportError: No module named expat; use SimpleXMLTreeBuilder instead
```

`openpyxl` imports it, so `tools/golden.sh` and `generators/build_wb.py` are affected too.

**The fix is `brew upgrade python@3.14`, and it is the repository owner's to run** — do not modify
the shared Homebrew installation or the `.venv` in service of this plan.

Until it is fixed, the baseline green state is:

```bash
cd practicesets && .venv/bin/pytest -q --ignore=tests/test_topdf_names.py
# 20 passed, 1 xfailed
```

Every task below uses that command. The xfail is `thornemeadow` in
`test_exactly_one_document_evidences_each_transaction`, is `strict=True`, and is pre-existing —
if it ever turns into a pass, that is someone else's change, not this plan's.

## A note on figures

This deliverable is content. Where a step writes `<amount>` or `# ... four or five in total`, that
is an **authored figure, constrained by the sentence that follows it** — not a placeholder to be
filled in later or left. The figures are chosen during implementation and proved mechanically: the
trial balance must net to zero, every subsidiary ledger must tie to its control to the cent, every
designed trap must still foot, and both clearing accounts must empty. A step is done when its
tests pass, not when its markers are gone.

`profile.CHECKPOINTS` is **not** this plan's business. It lives at
`originalentry/packs/<slug>/profile.py` and exists only to translate a paper set into an app pack,
which is deferred. On paper, the checkpoints are authored prose in `GUIDE_SCHEDULE` (Task 7) and
the control proofs `generators/gensolution.py:209` emits for each subsidiary ledger (Task 8).

## Global Constraints

Copied verbatim from the spec. Every task's requirements implicitly include these.

- **Every designed error leaves the trial balance in balance.** The traps are invisible to footing
  and visible only by reading individual accounts. This is the catalog's central design rule.
- **Beginning work in process is zero.** The shop finishes every open job before the holiday
  shutdown and the set opens on the first working day after. A labelled figure row with no account
  inflates the marks denominator in `statements_figures` while earning nothing, so the schedule
  must need no opening-WIP row.
- **A sole proprietor is not an employee.** M. Ashgrove works the bench, but the proprietor's own
  labour is never a cost of the business and never reaches a job cost sheet. Money taken out is a
  withdrawal of capital, not wages. The two family members *are* employees.
- **Overhead is actual, not a predetermined rate.** Charged to a job in proportion to the direct
  labour hours on its cost sheet, **as each job completes**, with a final entry for the still-open
  jobs leaving `505 Factory Overhead` nil. No under- or over-applied balance.
- **No document states the answer.** `tests/test_documents_do_not_answer_themselves.py` forbids
  these phrases anywhere on a document's face: `"no accounting entry"`,
  `"discount period has passed"`, `"nothing is owed"`.
- **`112 Work in Process` carries `subsidiary_kind="job"`** and its control must equal the sum of
  the open job cost sheets, to the cent, in every variant.
- **Three variants**, A/B/C, on two drivers: `P1` (the contract price of the flagship kitchen) and
  `QTY` (board feet of the principal lumber purchase). The combinatorial-variants design is a
  separate unstarted project; use the existing three-variant mechanism.
- **`MINI_CLOSE = None`.** The proprietorship closing appendix is deliberately out of scope for
  version one.
- **Accounts `110`, `301 Common Stock`, `302 Retained Earnings` and `303 Dividends` do not exist.**
  Equity is `301 M. Ashgrove, Capital`, `302 M. Ashgrove, Drawing`, `399 Income Summary`.
- **No module-level `print()`.** `companies/riverbend.py:490` has one and it makes every generator
  run chatty. Do not copy it.

## Review Focus

Five failure modes the spec implies that the generators' own verifiers do not catch. Each has a
test in the task that owns it.

1. **Beginning work in process is not zero** — `OPENING` carries a balance for `112`, so the
   schedule needs an opening row that leaks marks. *Pinned in Task 2.*
2. **`505 Factory Overhead` is not nil at period end** — overhead was incurred but never fully
   charged to jobs, so the schedule's overhead line understates and work in process is wrong.
   *Pinned in Task 4.*
3. **The proprietor's labour reaches a job cost sheet** — the owner's hours or draw appear in
   direct labour, contradicting the case's central proprietorship lesson. *Pinned in Task 4.*
4. **The work in process control does not equal the sum of the open job cost sheets** — the third
   subsidiary ledger is a claim the books do not support, and the fourth checkpoint is a lie.
   *Pinned in Task 4.*
5. **A designed trap unbalances the trial balance** — the error becomes visible to footing, which
   destroys the one lesson the whole catalog is built to deliver. *Pinned in Task 5.*

---

### Task 1: Make the no-self-answering guard company-aware

`test_the_documents_that_need_no_entry_still_say_what_they_are` is parametrized over `COMPANIES`
but its body asserts text only the veterinary clinic has — `"APPOINTMENT REQUEST"`,
`"after 12 January"`, `"No treatment has been given"`, `"Nothing has been ordered against"`.
Adding a fourth company to `COMPANIES` makes it fail for reasons that have nothing to do with the
fourth company. This task generalises it before any company is added. No company module yet.

**Files:**
- Modify: `practicesets/tests/test_documents_do_not_answer_themselves.py:78-90`

**Interfaces:**
- Consumes: nothing.
- Produces: `STILL_SAY_WHAT_THEY_ARE: dict[str, tuple[tuple[str, str], ...]]` — maps a company slug
  to pairs of `(a substring identifying the document, a substring that must appear in it)`. Task 6
  adds Ashgrove's entry.

- [ ] **Step 1: Write the failing test**

Add to `practicesets/tests/test_documents_do_not_answer_themselves.py`:

```python
# Per company: which no-entry document to find, and the fact that must have survived the footer's
# removal. Keyed by a substring that identifies the document among the version-A artefacts.
STILL_SAY_WHAT_THEY_ARE = {
    "alderfinch": (
        ("APPOINTMENT REQUEST", "after 12 January"),
        ("APPOINTMENT REQUEST", "No treatment has been given"),
        ("From 1 Jan", "Nothing has been ordered against"),
    ),
}


def test_every_cleared_company_declares_what_its_no_entry_documents_must_still_say():
    """A company cleared of self-answering text but with no expectations here would pass the
    guard below vacuously. The guard is only as good as this table."""
    assert set(STILL_SAY_WHAT_THEY_ARE) == set(COMPANIES)
```

- [ ] **Step 2: Run it to verify it passes, then watch it fail for the right reason**

```bash
cd practicesets && .venv/bin/pytest -q \
  tests/test_documents_do_not_answer_themselves.py::test_every_cleared_company_declares_what_its_no_entry_documents_must_still_say
```
Expected: PASS (`COMPANIES` is `("alderfinch",)` and the table has exactly that key).

Now prove the guard is live by temporarily adding `"ashgrove"` to `COMPANIES` and re-running:
Expected: FAIL with the sets differing. **Remove `"ashgrove"` again before continuing** — Task 2
adds it properly.

- [ ] **Step 3: Replace the clinic-specific body with the table**

Replace the body of `test_the_documents_that_need_no_entry_still_say_what_they_are` with:

```python
@pytest.mark.parametrize("company", COMPANIES)
def test_the_documents_that_need_no_entry_still_say_what_they_are(company):
    """The footers went; the facts stayed. Removing the judgement must not leave a student unable
    to reach it -- an appointment request still has to read as a request for a future appointment,
    and a price list as a notice nothing was ordered against."""
    documents = _documents(company)

    missing = []
    for identifier, must_say in STILL_SAY_WHAT_THEY_ARE[company]:
        matches = [html for html in documents.values() if identifier in html]
        if not matches:
            missing.append(f"no document contains {identifier!r}")
        elif not any(must_say in html for html in matches):
            missing.append(f"the document with {identifier!r} no longer says {must_say!r}")

    assert not missing, f"{company}: {missing}"
```

- [ ] **Step 4: Run the suite to verify alderfinch still passes**

```bash
cd practicesets && .venv/bin/pytest -q --ignore=tests/test_topdf_names.py
```
Expected: 21 passed, 1 xfailed (one more test than the baseline's 20).

- [ ] **Step 5: Commit**

```bash
cd practicesets
git add tests/test_documents_do_not_answer_themselves.py
git commit -m "Let a fourth company join the cleared list

The guard that proves a no-entry document still says what it is was
parametrized over COMPANIES but asserted text only the clinic has. A
fourth company added to that list would fail it for reasons of the
clinic's, not its own. The expectations are now a table keyed by
company, and a second test proves the table covers the list -- so a
company cleared of self-answering text cannot pass the guard vacuously."
```

---

### Task 2: The company, its chart, its period and its opening balances

Creates the module with everything that is static data, and a `build()` that returns no
transactions yet. The declaration gate in
`test_documents_do_not_answer_themselves.py::test_every_company_is_in_exactly_one_list` asserts
`on_disk == declared`, so the file and the list entry must land in the same commit.

**Files:**
- Create: `practicesets/companies/ashgrove.py`
- Create: `practicesets/tests/test_ashgrove_cost_flow.py`
- Modify: `practicesets/tests/test_documents_do_not_answer_themselves.py` (add `"ashgrove"` to `COMPANIES` and to `STILL_SAY_WHAT_THEY_ARE`)

**Interfaces:**
- Consumes: `STILL_SAY_WHAT_THEY_ARE` from Task 1.
- Produces, for Tasks 3–8: `money(x) -> Decimal`; `COMPANY: dict`; `ACCOUNTS: list[tuple[int, str, str]]`;
  `ACCT_NAME: dict[int, str]`; `ACC: dict[str, int]` with keys including
  `CASH PETTY AR RAW WIP FINISHED AP CAPITAL DRAWING SALES COGS FOH WAGES`;
  `PERIOD: dict`; `day(n) -> str`; `CUSTOMERS`, `VENDORS`, `LATE_VENDORS`, `CUSTOMER_INFO`,
  `VENDOR_INFO`, `EMPLOYEES`, `SKUS`, `ITEM_DESC_EXTRA`, `OPENING: dict[int, int|float]`,
  `VARIANTS: dict[str, dict[str, int]]`, `SLUG: str`, `build(variant="B") -> list[dict]`,
  `trial_balance(T) -> tuple[dict, dict]`.

- [ ] **Step 1: Write the failing tests**

Create `practicesets/tests/test_ashgrove_cost_flow.py`:

```python
"""The invariants this case introduces, which the shared verifiers do not know about.

verify.py proves receivables and payables tie to their controls. A manufacturer adds a third
subsidiary ledger and a cost flow, and those are what this file guards.
"""

from __future__ import annotations

import importlib
from decimal import Decimal as D

import pytest

ashgrove = importlib.import_module("companies.ashgrove")

VARIANTS = ("A", "B", "C")


def test_the_opening_trial_balance_nets_to_zero():
    """A set whose opening books do not tie cannot be worked at all."""
    assert sum(D(str(v)) for v in ashgrove.OPENING.values()) == 0


def test_the_shop_starts_with_no_open_jobs():
    """Beginning work in process is zero by design: the cost of goods manufactured schedule needs
    no opening row, and a labelled figure row with no account would leak marks (see the spec)."""
    assert ashgrove.OPENING.get(ashgrove.ACC["WIP"], 0) == 0


def test_the_chart_has_no_merchandise_inventory_and_no_corporate_equity():
    """A manufacturer makes what it sells, and a proprietorship has no stock or dividends."""
    names = {name.lower() for _, name, _ in ashgrove.ACCOUNTS}
    for forbidden in ("merchandise inventory", "common stock", "retained earnings", "dividends"):
        assert forbidden not in names, f"{forbidden!r} does not belong in this chart"


def test_the_chart_has_the_three_inventory_accounts_and_the_proprietor():
    names = {name.lower() for _, name, _ in ashgrove.ACCOUNTS}
    assert "raw materials inventory" in names
    assert "work in process" in names
    assert "finished goods inventory" in names
    assert any("capital" in n for n in names)
    assert any("drawing" in n for n in names)


@pytest.mark.parametrize("variant", VARIANTS)
def test_every_variant_balances(variant):
    balances, _ = ashgrove.trial_balance(ashgrove.build(variant))
    debits = sum(x for x in balances.values() if x > 0)
    credits = -sum(x for x in balances.values() if x < 0)
    assert debits == credits, f"variant {variant} is off by {debits - credits}"
```

- [ ] **Step 2: Run them to verify they fail**

```bash
cd practicesets && .venv/bin/pytest -q tests/test_ashgrove_cost_flow.py
```
Expected: collection error — `ModuleNotFoundError: No module named 'companies.ashgrove'`.

- [ ] **Step 3: Create the module's static data**

Create `practicesets/companies/ashgrove.py`. Follow `companies/riverbend.py` for structure and
for the HTML-entity convention in letterhead strings (the generators interpolate them unescaped).

```python
"""Ashgrove Millwork - custom cabinet shop, sole proprietorship, Dec 1-18."""
from decimal import Decimal as D

def money(x): return D(str(x)).quantize(D('0.01'))

COMPANY = dict(
    name="Ashgrove Millwork",
    caps="ASHGROVE MILLWORK",
    # ... address, telephone, proprietor line: follow riverbend's COMPANY keys exactly
)

ACCOUNTS = [
 (101,"Cash","A"),(102,"Petty Cash","A"),(105,"Accounts Receivable","A"),
 (106,"Allowance for Doubtful Accounts","XA"),
 (111,"Raw Materials Inventory","A"),(112,"Work in Process","A"),
 (113,"Finished Goods Inventory","A"),
 (115,"Office Supplies","A"),(116,"Prepaid Insurance","A"),
 (150,"Shop Equipment","A"),(151,"Accum. Depreciation - Shop Equipment","XA"),
 (155,"Delivery Truck","A"),(156,"Accum. Depreciation - Delivery Truck","XA"),
 (201,"Accounts Payable","L"),(203,"Wages Payable","L"),(204,"FICA Taxes Payable","L"),
 (205,"Federal Income Tax Withheld Payable","L"),
 (206,"State Income Tax Withheld Payable","L"),(207,"Unemployment Taxes Payable","L"),
 (210,"Interest Payable","L"),(215,"Customer Deposits on Jobs","L"),(220,"Notes Payable","L"),
 (301,"M. Ashgrove, Capital","E"),(302,"M. Ashgrove, Drawing","E"),(399,"Income Summary","E"),
 (401,"Cabinetry Sales","R"),(402,"Sales Returns and Allowances","XR"),
 (403,"Sales Discounts","XR"),
 (501,"Cost of Goods Sold","X"),(505,"Factory Overhead","X"),(506,"Factory Wages","X"),
 (511,"Showroom Salaries Expense","X"),(513,"Payroll Tax Expense","X"),
 (514,"Rent Expense","X"),(515,"Advertising Expense","X"),(516,"Delivery Expense","X"),
 (517,"Office Supplies Expense","X"),(518,"Insurance Expense","X"),
 (521,"Bad Debts Expense","X"),(522,"Utilities Expense","X"),
 (523,"Bank Service Charge Expense","X"),(590,"Interest Expense","X"),
]
ACCT_NAME = {n: name for n, name, _ in ACCOUNTS}

ACC = dict(CASH=101, PETTY=102, AR=105, RAW=111, WIP=112, FINISHED=113,
           SUPPLIES=115, AP=201, CAPITAL=301, DRAWING=302,
           SALES=401, RETURNS=402, DISCOUNTS=403,
           COGS=501, FOH=505, WAGES=506)

PERIOD = dict(
    month="Dec", label="1-18 December", prose="1 to 18 December",
    ends="18 December", ends_short="Dec 18",
    working_days=(1, 2, 3, 4, 5, 8, 9, 10, 11, 12, 15, 16, 17, 18),
    hours_per_day=8.0,
)
PERIOD["hours"] = len(PERIOD["working_days"]) * PERIOD["hours_per_day"]


def day(n):
    """A working day as the documents write it."""
    return f"{PERIOD['month']} {n}"


VARIANTS = {"A": {"P1": 7200, "QTY": 900},
            "B": {"P1": 7500, "QTY": 960},
            "C": {"P1": 7800, "QTY": 1020}}
SLUG = "Ashgrove"
```

Then author `CUSTOMER_INFO`, `VENDOR_INFO`, `EMPLOYEES`, `SKUS`, `ITEM_DESC_EXTRA`, `CUSTOMERS`,
`VENDORS`, `LATE_VENDORS` and `OPENING` on riverbend's pattern.

`EMPLOYEES` holds **the two family members only**, never the proprietor — a sole proprietor is not
an employee (Global Constraints). `SKUS` are the shop's materials and its standard cabinet
components, keyed `M-01`, `M-02`, … for materials.

`OPENING` is 30 November, debit positive, and **must set `112` to 0** and must net to zero. The
nominal accounts carry eleven months of figures, as Riverbend's do.

Add a `build()` returning an empty list and a `trial_balance()` copied from
`companies/riverbend.py:582-589` — it is identical in all three companies:

```python
def build(variant="B"):
    return []


def trial_balance(T):
    bal={k:D(str(v)) for k,v in OPENING.items()}
    dec={}
    for tr in T:
        for acct,dr,cr in tr["lines"]:
            delta=money(D(str(dr))-D(str(cr)))
            bal[acct]=money(bal.get(acct,D(0))+delta); dec[acct]=money(dec.get(acct,D(0))+delta)
    return bal,dec
```

- [ ] **Step 4: Declare the company in both lists**

In `practicesets/tests/test_documents_do_not_answer_themselves.py`, change
`COMPANIES = ("alderfinch",)` to `COMPANIES = ("alderfinch", "ashgrove")` and add an `"ashgrove"`
key to `STILL_SAY_WHAT_THEY_ARE` with an empty tuple for now:

```python
    # Filled in by Task 6, when the no-entry documents exist.
    "ashgrove": (),
```

- [ ] **Step 5: Run the new tests to verify they pass**

```bash
cd practicesets && .venv/bin/pytest -q tests/test_ashgrove_cost_flow.py
```
Expected: PASS. `test_every_variant_balances` passes trivially on an empty transaction list
because the opening balances net to zero; Task 3 gives it work to do.

- [ ] **Step 6: Run the whole suite**

```bash
cd practicesets && .venv/bin/pytest -q --ignore=tests/test_topdf_names.py
```
Expected: all pass except the known `thornemeadow` xfail. The document-level tests parametrized
over `COMPANIES` now run for `ashgrove` against a company with no documents — if any fails,
**do not weaken it**; it is telling you Task 6's work is a prerequisite it cannot see. Note which,
and if the failure is "no documents emitted", skip those by marking the ashgrove parameter
`pytest.mark.xfail(strict=True, reason="documents arrive in Task 6")` and remove the marker in
Task 6.

- [ ] **Step 7: Commit**

```bash
cd practicesets
git add companies/ashgrove.py tests/test_ashgrove_cost_flow.py \
        tests/test_documents_do_not_answer_themselves.py
git commit -m "Author Ashgrove Millwork's chart, period and opening books

The catalog's fourth case and its first manufacturer: a custom cabinet
shop, sole proprietorship. Three inventory accounts where the
merchandisers have one, a factory overhead and a factory wages clearing
account so the direct/indirect decision is an entry the student makes,
and capital and drawing where the other three have common stock and
dividends.

Work in process opens at nil. The shop finishes its jobs before the
shutdown, which is what lets the cost of goods manufactured schedule do
without an opening row -- a labelled figure row carrying no account
would inflate the marks denominator while earning nothing."
```

---

### Task 3: The journals and the transactions

**Files:**
- Modify: `practicesets/companies/ashgrove.py`

**Interfaces:**
- Consumes: everything Task 2 produced.
- Produces: `JOURNALS: list[dict]`; `journals() -> list[dict]`; a `build(variant)` returning the
  full transaction list, each entry a dict with keys `no date cycle doc desc lines ar ap note
  items meta` exactly as `companies/riverbend.py:496-520` builds them.

- [ ] **Step 1: Write the failing tests**

Append to `practicesets/tests/test_ashgrove_cost_flow.py`:

```python
@pytest.mark.parametrize("variant", VARIANTS)
def test_the_set_is_the_size_the_spec_promises(variant):
    """About thirty recordable transactions. Riverbend is twenty-eight in five and a half hours;
    this case is budgeted at six."""
    assert 26 <= len(ashgrove.build(variant)) <= 34


@pytest.mark.parametrize("variant", VARIANTS)
def test_cost_flows_through_all_three_inventory_accounts(variant):
    """What makes this a manufacturer rather than a merchandiser. Raw materials must be
    requisitioned, work in process must be relieved into finished goods, and finished goods must
    be relieved into cost of goods sold."""
    transactions = ashgrove.build(variant)
    debited, credited = set(), set()
    for transaction in transactions:
        for account, dr, cr in transaction["lines"]:
            if dr: debited.add(account)
            if cr: credited.add(account)

    for account, side, names in (
        (ashgrove.ACC["RAW"], credited, "raw materials requisitioned out"),
        (ashgrove.ACC["WIP"], debited, "cost charged to jobs"),
        (ashgrove.ACC["WIP"], credited, "jobs transferred to finished goods"),
        (ashgrove.ACC["FINISHED"], debited, "jobs received into finished goods"),
        (ashgrove.ACC["FINISHED"], credited, "finished goods sold"),
        (ashgrove.ACC["COGS"], debited, "cost of goods sold recognised"),
    ):
        assert account in side, f"variant {variant}: no {names}"


@pytest.mark.parametrize("variant", VARIANTS)
def test_every_transaction_balances_on_its_own(variant):
    """A set whose individual entries do not balance cannot be posted, whatever the totals say."""
    for transaction in ashgrove.build(variant):
        debits = sum(D(str(dr)) for _, dr, _ in transaction["lines"])
        credits = sum(D(str(cr)) for _, _, cr in transaction["lines"])
        assert debits == credits, (
            f"variant {variant} txn {transaction['no']} ({transaction['desc']}) "
            f"is off by {debits - credits}"
        )


@pytest.mark.parametrize("variant", VARIANTS)
def test_the_drivers_move_the_figures(variant):
    """Three versions exist so no student can work from a classmate's numbers. If a driver moves
    and nothing downstream moves, the versions are the same set with different covers."""
    if variant == "B":
        pytest.skip("B is the reference")
    reference, _ = ashgrove.trial_balance(ashgrove.build("B"))
    theirs, _ = ashgrove.trial_balance(ashgrove.build(variant))
    moved = [a for a in reference if reference[a] != theirs.get(a)]
    assert len(moved) >= 8, f"variant {variant} differs from B in only {len(moved)} accounts"
```

- [ ] **Step 2: Run them to verify they fail**

```bash
cd practicesets && .venv/bin/pytest -q tests/test_ashgrove_cost_flow.py
```
Expected: the four new tests FAIL — `build()` returns an empty list, so the size assertion fails
and no account appears on either side.

- [ ] **Step 3: Author JOURNALS and journals()**

Five journals, as `companies/riverbend.py:105-150` declares them: sales, purchases, cash receipts,
cash payments, general. Copy `journals()` verbatim from `companies/riverbend.py:256-266` — it is
identical in all three companies.

The sales journal's cost column becomes finished goods rather than merchandise inventory:

```python
      amounts=[("A/R Dr — Sales Cr","17%","(105) / (401)",()),
               ("COGS Dr — Finished Goods Cr","18%","(501) / (113)",("FINISHED","COGS"))],
```

and the purchases journal's stock column becomes raw materials:

```python
      amounts=[("Raw Materials Dr","14%","(111)",("RAW",)),
               ("Office Supplies Dr","14%","(115)",()),
               ("A/P Cr","14%","(201)",())],
```

Requisitions, time tickets, the overhead charge and the owner's drawings are general journal
entries. Do not add a sixth journal: a manufacturer's distinguishing entries are occasional, and a
special journal for them would imply a volume this shop does not have.

- [ ] **Step 4: Author build()**

Follow `companies/riverbend.py:496-580`: a local `t(...)` helper appending to `T`, plus `sale(...)`
and `cashsale(...)` closures that compute revenue and cost from `SKUS` and the drivers.

The cost flow, from the spec, in the order the shop lives it:

| Event | Entry |
| --- | --- |
| Lumber and hardware bought | `RAW` dr · `AP` cr |
| Direct materials requisitioned to a job | `WIP` dr · `RAW` cr |
| Indirect materials requisitioned | `FOH` dr · `RAW` cr |
| Payroll paid | `WAGES` dr · withholdings cr · `CASH` cr |
| Wages distributed | `WIP` dr (direct) · `FOH` dr (indirect shop) · `511` dr (period) · `WAGES` cr |
| Other shop cost incurred | `FOH` dr · `CASH`/`AP` cr |
| Overhead charged to a job | `WIP` dr · `FOH` cr — as each job completes, and finally to the open jobs |
| Job completed | `FINISHED` dr · `WIP` cr — at accumulated cost |
| Job delivered and invoiced | `AR` dr · `SALES` cr, and `COGS` dr · `FINISHED` cr |
| Owner takes money out | `DRAWING` dr · `CASH` cr |

Four or five numbered jobs, at least one still open at 18 December so ending work in process is
not nil. Both drivers must reach every downstream figure: `P1` is the flagship kitchen's contract
price, `QTY` the board feet of the principal lumber purchase.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd practicesets && .venv/bin/pytest -q tests/test_ashgrove_cost_flow.py
```
Expected: PASS.

- [ ] **Step 6: Prove it against the shared verifier**

```bash
cd practicesets/companies && PRACTICESET_COMPANY=ashgrove ../.venv/bin/python ashgrove.py
```
Add the same `__main__` block `companies/riverbend.py:591-598` has, so this prints each variant's
transaction count and `BALANCED`. Expected: `BALANCED` for A, B and C.

```bash
cd practicesets/generators && PRACTICESET_COMPANY=ashgrove ../.venv/bin/python verify.py
```
Expected: `OK` for both A/R and A/P on all three variants. **If this says `MISMATCH`, stop** — a
set whose books do not tie is worse than no set, because the student cannot tell their error from
the author's.

- [ ] **Step 7: Commit**

```bash
cd practicesets
git add companies/ashgrove.py tests/test_ashgrove_cost_flow.py
git commit -m "Author Ashgrove's journals and its fortnight of work

Five journals as the merchandisers keep, with finished goods where they
have merchandise inventory and raw materials where they have stock.
Requisitions, the wage distribution, the overhead charge and the owner's
drawings go to the general journal: these entries are occasional, and a
special journal for them would imply a volume this shop does not have.

Cost now flows all the way through -- raw materials requisitioned to a
job, wages split three ways between a job, the shop and the showroom,
overhead charged as each job completes, finished work transferred at
accumulated cost, and only then sold."
```

---

### Task 4: The job cost sheet ledger and the cost-flow invariants

The case's third subsidiary ledger. `verify.py` knows only about receivables and payables, so the
work in process control is unguarded by anything shared — and three of the five traps corrupt it.

**Files:**
- Modify: `practicesets/companies/ashgrove.py`
- Modify: `practicesets/tests/test_ashgrove_cost_flow.py`

**Interfaces:**
- Consumes: `build`, `trial_balance`, `ACC` from Tasks 2–3.
- Produces: `JOBS: dict[str, tuple[str, str]]` mapping a job number to
  `(customer code, what the job is)`; and every transaction that touches `ACC["WIP"]` carrying
  `meta={"job": "<job number>"}` so a cost sheet can be rebuilt from the transaction list.

- [ ] **Step 1: Write the failing tests**

Append to `practicesets/tests/test_ashgrove_cost_flow.py`:

```python
def _job_cost_sheets(variant):
    """Rebuild the subsidiary ledger from the transactions, the way a student builds it from the
    documents: every line touching work in process belongs to exactly one job."""
    sheets = {job: D(0) for job in ashgrove.JOBS}
    for transaction in ashgrove.build(variant):
        job = transaction["meta"].get("job")
        for account, dr, cr in transaction["lines"]:
            if account != ashgrove.ACC["WIP"]:
                continue
            assert job, (
                f"txn {transaction['no']} ({transaction['desc']}) moves work in process "
                f"without naming a job"
            )
            sheets[job] = ashgrove.money(sheets[job] + D(str(dr)) - D(str(cr)))
    return sheets


@pytest.mark.parametrize("variant", VARIANTS)
def test_the_work_in_process_control_equals_the_open_job_cost_sheets(variant):
    """The third subsidiary ledger, and the fourth checkpoint. A control that does not tie to its
    ledger is a claim the books do not support."""
    balances, _ = ashgrove.trial_balance(ashgrove.build(variant))
    control = balances[ashgrove.ACC["WIP"]]
    sheets = _job_cost_sheets(variant)
    total = ashgrove.money(sum(sheets.values()))
    detail = {job: str(amount) for job, amount in sheets.items()}
    assert total == control, (
        f"variant {variant}: control {control}, sheets {total} -- {detail}"
    )


@pytest.mark.parametrize("variant", VARIANTS)
def test_a_closed_job_leaves_its_sheet_at_nil_and_an_open_one_does_not(variant):
    """Ending work in process is the sum of the sheets still open. If every sheet closed, the
    schedule's last line would be nil and the case would never show an unfinished job."""
    sheets = _job_cost_sheets(variant)
    open_sheets = {job: total for job, total in sheets.items() if total != 0}
    assert open_sheets, f"variant {variant}: no job is still open at the period end"
    assert all(total > 0 for total in open_sheets.values()), (
        f"variant {variant}: a job cost sheet is overdrawn: {open_sheets}"
    )


@pytest.mark.parametrize("variant", VARIANTS)
def test_factory_overhead_is_nil_at_the_period_end(variant):
    """Actual overhead is charged to jobs as they complete, with a final entry for the open ones.
    A residue means the schedule's overhead line understates and work in process is wrong."""
    balances, _ = ashgrove.trial_balance(ashgrove.build(variant))
    assert balances[ashgrove.ACC["FOH"]] == 0, (
        f"variant {variant}: factory overhead carries {balances[ashgrove.ACC['FOH']]}"
    )


@pytest.mark.parametrize("variant", VARIANTS)
def test_factory_wages_is_nil_at_the_period_end(variant):
    """The clearing account exists so the direct/indirect/period split is an entry the student
    makes. Left with a balance, the split never happened."""
    balances, _ = ashgrove.trial_balance(ashgrove.build(variant))
    assert balances[ashgrove.ACC["WAGES"]] == 0, (
        f"variant {variant}: factory wages carries {balances[ashgrove.ACC['WAGES']]}"
    )


@pytest.mark.parametrize("variant", VARIANTS)
def test_the_proprietors_money_never_reaches_a_job(variant):
    """A sole proprietor is not an employee. The owner's labour is never a cost of the business,
    so a drawing must not pass through the wage clearing account into a job cost sheet."""
    for transaction in ashgrove.build(variant):
        accounts = {account for account, _, _ in transaction["lines"]}
        if ashgrove.ACC["DRAWING"] in accounts:
            assert ashgrove.ACC["WAGES"] not in accounts, (
                f"variant {variant} txn {transaction['no']}: a drawing touches factory wages"
            )
            assert ashgrove.ACC["WIP"] not in accounts, (
                f"variant {variant} txn {transaction['no']}: a drawing touches work in process"
            )
```

- [ ] **Step 2: Run them to verify they fail**

```bash
cd practicesets && .venv/bin/pytest -q tests/test_ashgrove_cost_flow.py \
  -k "job or overhead or wages or proprietor"
```
Expected: FAIL — `AttributeError: module 'companies.ashgrove' has no attribute 'JOBS'`, and the
work-in-process lines carry no `meta["job"]`.

- [ ] **Step 3: Declare JOBS and tag every work-in-process line**

Add to `practicesets/companies/ashgrove.py`:

```python
# ── The jobs on the floor ───────────────────────────────────────────────────────────────
#
# One cost sheet per job, subsidiary to 112. A sheet is open until its job transfers to finished
# goods, so the sum of the open sheets is ending work in process -- the last line of the cost of
# goods manufactured schedule, and the fourth checkpoint.
JOBS = {
    "J-114": ("C-101", "Kitchen, 14 units, paint-grade maple"),
    # ... four or five in total, at least one still open at Dec 18
}
```

Then give every transaction whose `lines` touch `ACC["WIP"]` a `meta={"job": "J-nnn"}`. The
overhead charge and the wage distribution each touch several jobs, so split them into one
transaction per job rather than one entry with a `WIP` line per job — a student posts from a
document to a sheet, and one document names one job.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd practicesets && .venv/bin/pytest -q tests/test_ashgrove_cost_flow.py
```
Expected: PASS, all variants.

- [ ] **Step 5: Commit**

```bash
cd practicesets
git add companies/ashgrove.py tests/test_ashgrove_cost_flow.py
git commit -m "Give Ashgrove its job cost sheets, and guard what ties them

One sheet per job, subsidiary to work in process. The sum of the open
sheets is ending work in process, which makes it the schedule's last
line and the set's fourth checkpoint -- so a student can find a cost
error during the work rather than after it.

verify.py knows only receivables and payables, and three of this case's
five traps corrupt the sheets instead, so the invariants are guarded
here: the control ties to the sheets, no job is overdrawn, both clearing
accounts empty by the period end, and the proprietor's drawings never
reach a job. A sole proprietor is not an employee and the owner's labour
is not a cost of the business."
```

---

### Task 5: The five designed traps

**Files:**
- Modify: `practicesets/companies/ashgrove.py`
- Modify: `practicesets/tests/test_ashgrove_cost_flow.py`

**Interfaces:**
- Consumes: `build`, `trial_balance`, `ACC`, `VARIANTS` from Tasks 2–4.
- Produces: `COMPANY_TRAPS: list[dict]`, each with keys `key date txn desc lines`, where
  `lines` is `lambda P1, QTY: [(account, debit, credit), ...]` giving the **wrong** entry. Read by
  `generators/errors.py`, which replaces transaction `txn`'s lines with the lambda's result.

- [ ] **Step 1: Write the failing tests**

Append to `practicesets/tests/test_ashgrove_cost_flow.py`:

```python
TRAP_KEYS = ("indirect_materials", "indirect_labour", "period_cost",
             "transfer_at_price", "owners_draw")


def test_all_five_traps_are_declared():
    assert tuple(trap["key"] for trap in ashgrove.COMPANY_TRAPS) == TRAP_KEYS


@pytest.mark.parametrize("variant", VARIANTS)
@pytest.mark.parametrize("key", TRAP_KEYS)
def test_a_trap_leaves_the_trial_balance_in_balance(variant, key):
    """The catalog's central design rule, and the point to put on the board at the debrief. A
    student who believes a balanced trial balance proves their work is correct will carry that
    belief into practice."""
    trap = next(t for t in ashgrove.COMPANY_TRAPS if t["key"] == key)
    drivers = ashgrove.VARIANTS[variant]
    wrong = trap["lines"](drivers["P1"], drivers["QTY"])
    debits = sum(D(str(dr)) for _, dr, _ in wrong)
    credits = sum(D(str(cr)) for _, _, cr in wrong)
    assert debits == credits, f"{key} on {variant} is off by {debits - credits}"


@pytest.mark.parametrize("variant", VARIANTS)
@pytest.mark.parametrize("key", TRAP_KEYS)
def test_a_trap_actually_moves_an_account(variant, key):
    """A trap that changes nothing is not a trap. This is what catches a lines lambda that
    accidentally reproduces the correct entry."""
    trap = next(t for t in ashgrove.COMPANY_TRAPS if t["key"] == key)
    drivers = ashgrove.VARIANTS[variant]
    correct = next(t for t in ashgrove.build(variant) if t["no"] == trap["txn"])["lines"]
    wrong = trap["lines"](drivers["P1"], drivers["QTY"])
    assert sorted(map(tuple, wrong)) != sorted(map(tuple, correct)), (
        f"{key} on {variant} is the correct entry"
    )


@pytest.mark.parametrize("key", TRAP_KEYS)
def test_a_trap_names_a_transaction_that_exists(key):
    trap = next(t for t in ashgrove.COMPANY_TRAPS if t["key"] == key)
    numbers = {t["no"] for t in ashgrove.build("B")}
    assert trap["txn"] in numbers, f"{key} names transaction {trap['txn']}, which does not exist"
```

- [ ] **Step 2: Run them to verify they fail**

```bash
cd practicesets && .venv/bin/pytest -q tests/test_ashgrove_cost_flow.py -k trap
```
Expected: FAIL — `AttributeError: module 'companies.ashgrove' has no attribute 'COMPANY_TRAPS'`.

- [ ] **Step 3: Author COMPANY_TRAPS**

From the spec. Each lambda is the **wrong** entry and must foot internally. Follow
`companies/riverbend.py:234-255` for form.

```python
COMPANY_TRAPS = [
 dict(key="indirect_materials", date="Dec 3", txn=5,
      desc="Glue, abrasives and screws requisitioned to a job instead of to factory overhead",
      lines=lambda P1, QTY: [(ACC['WIP'],  <amount>, 0), (ACC['RAW'], 0, <amount>)]),
 dict(key="indirect_labour", date="Dec 9", txn=14,
      desc="Blade sharpening and stock moving written onto a job time ticket",
      lines=lambda P1, QTY: [(ACC['WIP'],  <amount>, 0), (ACC['WAGES'], 0, <amount>)]),
 dict(key="period_cost", date="Dec 1", txn=1,
      desc="The whole of the rent charged to the factory, showroom share included",
      lines=lambda P1, QTY: [(ACC['FOH'], <full rent>, 0), (ACC['CASH'], 0, <full rent>)]),
 dict(key="transfer_at_price", date="Dec 16", txn=26,
      desc="A finished job moved to stock at its contract price, not its accumulated cost",
      lines=lambda P1, QTY: [(ACC['FINISHED'], P1, 0), (ACC['WIP'], 0, P1)]),
 dict(key="owners_draw", date="Dec 12", txn=20,
      desc="The proprietor's withdrawal booked as further factory wages",
      lines=lambda P1, QTY: [(ACC['WAGES'], <draw>, 0), (ACC['CASH'], 0, <draw>)]),
]
```

Replace each `<...>` with the figure the correct entry uses, so the wrong entry differs only in
*which* account it names. For `transfer_at_price` the figure differs on purpose — the contract
price `P1` rather than the sheet's accumulated cost — which is the whole error.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd practicesets && .venv/bin/pytest -q tests/test_ashgrove_cost_flow.py
```
Expected: PASS.

- [ ] **Step 5: Prove it against the shared trap reporter**

```bash
cd practicesets/generators && PRACTICESET_COMPANY=ashgrove ../.venv/bin/python errors.py
```
Expected: for each of the five, `trial balance still balances: True`, and a list of the accounts
that moved. Read the account lists: each trap must move an account a student would have to *read*
to notice, never only a total. `transfer_at_price` must show work in process and finished goods
both wrong.

- [ ] **Step 6: Commit**

```bash
cd practicesets
git add companies/ashgrove.py tests/test_ashgrove_cost_flow.py
git commit -m "Author Ashgrove's five traps

Every one of them foots. That is the catalog's central rule and the
point to put on the board at the debrief: a balanced trial balance
proves nothing, and these are visible only by reading individual
accounts.

Four cannot occur in any existing case. transfer_at_price breaks the
work in process control against the job cost sheets, so the case's new
subsidiary ledger is what exposes it. owners_draw is impossible in a
corporation, where an officer's salary genuinely is an expense, and it
crosses from equity into inventory -- booked as wages, the draw passes
through the clearing account into work in process and inflates every job
the distribution touches."
```

---

### Task 6: The documents

**Files:**
- Modify: `practicesets/companies/ashgrove.py`
- Modify: `practicesets/tests/test_documents_do_not_answer_themselves.py` (fill in `STILL_SAY_WHAT_THEY_ARE["ashgrove"]`, drop any xfail marker added in Task 2 Step 6)
- Modify: `practicesets/tests/test_manifest.py` (add `"ashgrove"` to the parametrize list at line 70)

**Interfaces:**
- Consumes: `JOBS`, `build`, `DOCS` keys from Tasks 2–5.
- Produces: `DOCS: dict`; `DOC_STOCK: dict`; `no_entry_documents(ctx)`; `PAYROLL_PERIOD: str`;
  `PAYROLL_TXN: int`; `PAYROLL_SPLIT: dict`; `PR: dict`; `RESIDUALS: tuple`.

- [ ] **Step 1: Write the failing test**

Fill in the Task 1 table in `practicesets/tests/test_documents_do_not_answer_themselves.py`.
The three no-entry documents from the spec are an estimate for a job the customer has not
accepted, a lumber delivery note for stock already invoiced, and a supplier's statement of account
duplicating invoices already entered:

```python
    "ashgrove": (
        ("ESTIMATE", "No work has been authorised"),
        ("DELIVERY NOTE", "invoiced separately"),
        ("STATEMENT OF ACCOUNT", "for information"),
    ),
```

None of those strings may be `"no accounting entry"`, `"discount period has passed"` or
`"nothing is owed"` — `STATES_THE_ANSWER` forbids them, and they are the triage answer on the face
of the question.

- [ ] **Step 2: Run it to verify it fails**

```bash
cd practicesets && .venv/bin/pytest -q tests/test_documents_do_not_answer_themselves.py
```
Expected: FAIL — `gendocs.py` emits no documents for `ashgrove`, so no document contains
`'ESTIMATE'`.

- [ ] **Step 3: Author DOCS, DOC_STOCK, the payroll data and no_entry_documents**

`DOCS` on `companies/riverbend.py:174-233`'s pattern, with the new document kinds the spec names:
production order, materials requisition, time ticket, job cost sheet. Keep the familiar
ones — invoices, receiving reports, cheques, remittances, the payroll register, customer contracts
carrying deposits.

`no_entry_documents(ctx)` on `companies/riverbend.py:607-648`'s pattern. Riverbend's versions end
`<div class="foot">Enquiry only &middot; no accounting entry</div>`, which is exactly what this
case must not do. Write footers that state facts instead:

```python
    # The footers carry what the document is, never what to do about it. Deciding that is the
    # first thing marked, and a footer that answered it would be marking the author's work.
    page("c104","stock-white",body, kind="estimate", printed_ref="EST-0318")
```

`PR`, `PAYROLL_SPLIT` and `EMPLOYEES` must agree: the two family members only, split between the
shop and the showroom, and the wage distribution in `build()` must spend exactly what the payroll
register shows.

- [ ] **Step 4: Add ashgrove to the manifest tests**

In `practicesets/tests/test_manifest.py`, add `"ashgrove"` to the parametrize list at line 70,
alongside `"alderfinch"` and `"riverbend"`. Do not touch the `thornemeadow` xfail.

- [ ] **Step 5: Run the document tests to verify they pass**

```bash
cd practicesets && .venv/bin/pytest -q tests/test_documents_do_not_answer_themselves.py tests/test_manifest.py
```
Expected: PASS. `test_exactly_one_document_evidences_each_transaction` is the strict one — every
transaction needs exactly one document that is the evidence for it, and a purchase that prints
both an order and an invoice must mark only the invoice as the entry.

- [ ] **Step 6: Commit**

```bash
cd practicesets
git add companies/ashgrove.py tests/test_documents_do_not_answer_themselves.py tests/test_manifest.py
git commit -m "Print Ashgrove's envelope

Production orders, materials requisitions, time tickets and job cost
sheets, alongside the invoices and cheques the other sets have. Three
artefacts need no entry at all -- an estimate for unauthorised work, a
delivery note for stock invoiced separately, and a statement of account
sent for information.

None of the three says 'no accounting entry'. Riverbend's and Thorne &
Meadow's do, which puts the triage answer on the face of the question;
this set is in the cleared list from the start, and its footers carry
what each document is instead."
```

---

### Task 7: The prose, the guide and the solution notes

**Files:**
- Modify: `practicesets/companies/ashgrove.py`
- Modify: `practicesets/tests/test_solution_notes.py` (add `"ashgrove"` to `COMPANIES` at line 24)

**Interfaces:**
- Consumes: everything above.
- Produces the last of the 42 names: `BOOKLET_STORY`, `BOOKLET_STAFF`, `GUIDE_SUBTITLE`,
  `GUIDE_SCHEDULE`, `GUIDE_SCHEDULE_SUBTITLE`, `HONEST_CASE`, `OPENING_NOTE`, `SOLUTION_NOTES`,
  `MINI_CLOSE = None`, `ITEM_DESC_EXTRA`, `teaching_notes(ctx)`, `guide_product(ctx)`.

- [ ] **Step 1: Write the failing test**

Add `"ashgrove"` to `COMPANIES` at `practicesets/tests/test_solution_notes.py:24`:

```python
COMPANIES = ("riverbend", "alderfinch", "thornemeadow", "ashgrove")
```

That file asserts the cash-payments solution note names the cheque the packet voids, and that the
voided cheque is not one the journal enters.

- [ ] **Step 2: Run it to verify it fails**

```bash
cd practicesets && .venv/bin/pytest -q tests/test_solution_notes.py
```
Expected: FAIL — `ashgrove` has no `SOLUTION_NOTES`, or its cash payments note does not say which
cheque is void.

- [ ] **Step 3: Author the prose**

Follow `companies/riverbend.py:322-495`. `MINI_CLOSE = None`, as `alderfinch` and `thornemeadow`
both set it — the proprietorship closing appendix is out of scope for version one.

`GUIDE_SCHEDULE` must name **four** checkpoints, not Riverbend's two: cash, the receivables
control, the payables control and the work in process control. The fourth is the case's own, and it
is what lets a student catch a cost-flow error during the work — three of the five traps corrupt
the job cost sheets.

`SOLUTION_NOTES["cash_payments"]` must name the voided cheque explicitly, and that cheque must not
appear in any transaction's `lines`. `teaching_notes(ctx)` carries what the spec's "what it
teaches" section says: cost flow, "whose cost is this?", and that a sole proprietor is not an
employee.

`BOOKLET_STORY` must explain why the nominal accounts already carry figures, as
`OPENING_NOTE` does for the others, and must say that the shop finished its open jobs before the
shutdown — that is what makes beginning work in process nil, and a student who does not know it
will look for an opening balance that is not there.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd practicesets && .venv/bin/pytest -q --ignore=tests/test_topdf_names.py
```
Expected: all pass but the known `thornemeadow` xfail.

- [ ] **Step 5: Commit**

```bash
cd practicesets
git add companies/ashgrove.py tests/test_solution_notes.py
git commit -m "Write Ashgrove's booklet, guide and solution notes

The story says why the nominal accounts already carry eleven months, and
why work in process does not: the shop finished every open job before
the shutdown. A student who does not know that looks for an opening
balance that is not there.

MINI_CLOSE stays None. The proprietorship closing -- income summary to
capital, and a statement of owner's equity -- is the obvious second
pass, but version one is about cost flow and nothing else."
```

---

### Task 8: Build the whole set and prove nothing else moved

**Files:**
- Create: `practicesets/Ashgrove-Millwork/README.md`
- Modify: `practicesets/CASES.md`

**Interfaces:**
- Consumes: the finished `companies/ashgrove.py`.
- Produces: nothing other tasks read.

- [ ] **Step 1: Build every artefact**

```bash
cd practicesets/generators
OUT=/tmp/ashgrove-build && mkdir -p "$OUT"
export PRACTICESET_COMPANY=ashgrove PRACTICESET_OUT="$OUT"
../.venv/bin/python verify.py
../.venv/bin/python genbooks.py B
for V in A B C; do
  ../.venv/bin/python gendocs.py     "$V"
  ../.venv/bin/python genbooklet.py  "$V"
  ../.venv/bin/python gensolution.py "$V"
done
../.venv/bin/python genassembly.py
../.venv/bin/python genguide.py
ls -la "$OUT"
```
Expected: every command exits 0 and `$OUT` holds the documents, books, booklets, solutions,
assembly instructions and guide. `build_wb.py` is **skipped** — it needs `openpyxl`, which is
blocked by the expat breakage in the Prerequisite section. Note it as not run rather than
reporting the set complete.

- [ ] **Step 2: Read the solution and check the schedule**

Open the version-B solution and confirm the cost of goods manufactured schedule reads as the spec
sets it out, with no opening work in process line:

```
  Direct materials used                  x,xxx
  Direct labour                          x,xxx
  Factory overhead                       x,xxx
    Total manufacturing cost            xx,xxx
  Less work in process, 18 December      (x,xxx)
    Cost of goods manufactured          xx,xxx
```

If the generators do not emit a schedule, add it to `SOLUTION_NOTES` as authored prose with the
figures — this case is a paper set, and the schedule is marked from the instructor's key.

Then confirm the solution carries a **control proof for the job cost sheets**.
`generators/gensolution.py:209` emits a `Control proof: subsidiary total = account` box, and this
case has three subsidiary ledgers where the others have two. If only receivables and payables are
proved, the job ledger's checkpoint has no answer in the key — report it rather than editing the
generator, which is outside this plan's scope and shared with three cases in service.

- [ ] **Step 3: Prove Riverbend did not move**

```bash
cd practicesets && tools/golden.sh
```
Expected: `unchanged: N files match`. If it reports `OUTPUT MOVED`, a generator or a shared helper
was edited — this plan modifies no generator, so investigate rather than `--accept`.

If `golden.sh` cannot run because `openpyxl` is blocked, say so explicitly and fall back to:

```bash
cd practicesets/generators
OUT=$(mktemp -d) && PRACTICESET_COMPANY=riverbend PRACTICESET_OUT=$OUT ../.venv/bin/python verify.py
```
Expected: `OK` throughout, matching the figures in `tools/golden.sha256`'s `verify.txt` entry.

- [ ] **Step 4: Add the case to CASES.md**

Add a row to the table at `practicesets/CASES.md:12-18` and a `### Ashgrove Millwork` section
following the three that exist. State what it teaches that the others cannot, name its five traps,
and say plainly that it has been checked mechanically but not worked by a person — as `CASES.md`
already says of Alder & Finch and Thorne & Meadow.

Update the line reading *"Three practice sets for a first course in financial accounting"* to four,
and the sentence naming which cases are paper-only.

- [ ] **Step 5: Run the full suite one last time**

```bash
cd practicesets && .venv/bin/pytest -q --ignore=tests/test_topdf_names.py
```
Expected: all pass but the known `thornemeadow` xfail. Report the count, and report
`test_topdf_names.py` as not run with the reason.

- [ ] **Step 6: Commit**

```bash
cd practicesets
git add CASES.md Ashgrove-Millwork/
git commit -m "Add Ashgrove Millwork to the catalog

Four cases now, and the first that makes anything. CASES.md says what it
teaches that the merchandisers and the clinic cannot, and says plainly
that it has been checked mechanically but not worked through by a
person -- which is true of two of the other three as well, and is the
thing that document asks an instructor to fix before setting it.

The master workbook is not built: openpyxl cannot import on this
machine's python@3.14, whose pyexpat is linked against a system libexpat
that does not satisfy it. Everything else in the pipeline runs."
```

---

## After the plan

Two things the spec records as out of scope, which this plan deliberately does not touch:

1. **The proprietorship mini-close.** `MINI_CLOSE` stays `None`. Closing the nominal accounts to
   capital and producing a statement of owner's equity is the obvious second pass, and should wait
   until someone has worked a packet.
2. **The app import.** The cost of goods manufactured schedule cannot be graded by the browser app
   until a flow-aware statement row exists, because `statements_figures` compares account rows
   against balances and the schedule reports flows. That is its own project, and it is also what
   Thorne & Meadow's statements need.

One thing found while reading, which belongs to neither: `tests/test_manifest.py`'s `thornemeadow`
xfail reason says *"Txn 12, the owner's drawing"* — but `companies/thornemeadow.py` declares
`Common Stock`, `Retained Earnings` and `Dividends`. A corporation has no owner's drawing. Worth a
look independently of this plan.
