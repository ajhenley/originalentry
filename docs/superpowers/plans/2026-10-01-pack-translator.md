# Pack Translator Repair and Alder & Finch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair the dead paper-set-to-pack translator, prove it against the Riverbend pack already in service, and use it to bring Alder & Finch Veterinary Clinic online.

**Architecture:** `scripts/build_pack.py` becomes generic machinery that reads figures from the `practicesets` sibling checkout under `PRACTICESET_COMPANY`. Everything company-specific — identity, period, journals, cycle mapping, checkpoints, rubric, triage distractors — moves into `packs/<slug>/profile.py`. A test regenerates Riverbend and asserts it still matches the committed `source.json`, so the bridge cannot rot again unobserved.

**Tech Stack:** Python 3.13+, stdlib only in the translator. The app's own `originalentry.generator.build` and `originalentry.packs.validate` are the gates.

**Spec:** `docs/superpowers/specs/2026-10-01-pack-translator-design.md`

## Global Constraints

- Python >= 3.13; run everything with `.venv/bin/python` from the repository root.
- Run python as `.venv/bin/python -B` and pytest with `-p no:cacheprovider`. Stale bytecode has already made a failing test look like a passing one in this project.
- **The translator reads figures and invents none.** Every number in a pack traces to the practicesets model. This is the contract inherited from the script being replaced.
- **The practicesets repository is not modified.** It is paper-only by decision and is the source of the figures.
- A missing `practicesets` checkout stops the run with a message naming what is missing. Never degrade quietly — silent rot is the defect this work exists to fix.
- Dates in `source.json` are ISO strings (`"2026-12-01"`); money is integer cents.
- Account numbers are strings in pack JSON (`"105"`), integers in the practicesets model (`105`).
- No pack text may contain the words correct, incorrect, right or wrong (rule W1), nor a money figure written to one decimal place (rule W2).
- `tests/unit/test_riverbend_pack.py` must keep passing unchanged throughout — it guards the live pack's figures against the printed solution set.

## File Structure

| File | Responsibility |
| --- | --- |
| `scripts/build_pack.py` | Generic translator. Reads practicesets, emits `source.json`. Knows no company. |
| `packs/riverbend/profile.py` | Riverbend's identity, period, journals, cycle map, checkpoints, rubric, distractors, reference pages. |
| `packs/alderfinch/profile.py` | The same for the clinic. Three journals; Purchases folds into the General Journal. |
| `packs/alderfinch/source.json` | Generated. Never hand-edited. |
| `tests/unit/test_build_pack.py` | The translator's own behaviour: loud failure, company isolation. |
| `tests/unit/test_pack_reproducible.py` | Regenerating Riverbend reproduces the committed `source.json`. |
| `tests/unit/test_alderfinch_pack.py` | The clinic's figures against the paper solution, modelled on `test_riverbend_pack.py`. |
| `scripts/build_riverbend.py` | Deleted in Task 3, once `build_pack.py` reproduces its output. |

## What is Riverbend-specific in the translator

Established by reading all 533 lines. There is no `if` on a company name anywhere — every
Riverbend fact is a flat literal, which is why a second company cannot be expressed without
moving them. Tasks 3 and 4 move this list, and nothing on it may be left behind:

| Lines | What | Why it breaks for the clinic |
| --- | --- | --- |
| 30 | `DEFAULT_SET` | Names a directory that no longer exists. Task 1. |
| 33–45 | `_load` call site passes `03-Source` | That path is gone. Task 1. |
| 201–213 | `_cheques` parses `gendocs.py` with `ast` | **Already broken for every company.** Task 1. |
| 64 | `NON_CURRENT = {"150","151","155","156"}` | The clinic has only 150 and 151. |
| 65–66 | `ROLES` | Keyed by account number. |
| 67 | `SUBSIDIARY` | Keyed by account number. |
| 70–71 | `JOURNAL_OF` | `KeyError` on the clinic's `Fees` cycle. |
| 74–118 | `journals()` | Five journals with COGS and inventory columns. |
| 121–160 | `reference()` | Reads `model.SKUS` and prints "Riverbend keeps a perpetual inventory". |
| 166–193 | `NO_ENTRY_DOCUMENTS` | Bicycle content dated 15 December. |
| 216–232 | `_face_amount` | Hardcodes accounts 101/105/201. |
| 239–305 | `_text_alternative` | Hardcodes transaction numbers 18, 24, 25, 26, 27. |
| 316 | `documents()` calls `model.build("B")` | Hardcoded base variant. |
| 346–349 | `_iso_date` | Hardcodes `2026-12-`. |
| 444–448, 459 | literal party `V-206` Kestrel Office Supply | **Would invent a vendor the clinic does not have.** |
| 488–493 | `company` block | Identity. |
| 495–496 | `period` | 1–15 December. |
| 508–517 | `checkpoints` | Accounts 105/101/201, prompts saying "at 15 December". |
| 519–525 | `rubric` | Component points. |

Also note line 385: `wrong_of` is assigned, never used, and discarded with `_ = wrong_of` at line
417. It calls `errors_mod.mutate(variant, "freight")`, and `freight` is a Riverbend trap kind.
Delete it in Task 1 rather than carrying dead code into the generic machinery.

---

### Task 1: Make the translator run again, and fail loudly when it cannot

**Files:**
- Create: `scripts/build_pack.py` (start as a copy of `scripts/build_riverbend.py`)
- Create: `tests/unit/test_build_pack.py`

**Interfaces:**
- Produces: `require_practicesets(path: Path) -> Path` returning the `generators` directory; `load_model(generators: Path, company: str) -> tuple[ModuleType, ModuleType]` returning `(model, errors)`; `build_source(company: str, practicesets: Path) -> dict`.

Context the implementer needs: `scripts/build_riverbend.py` currently reads `Riverbend-Paper-Practice-Set/03-Source/`, a directory that no longer exists, so its documented command raises `FileNotFoundError`. The same modules now live at `practicesets/generators/model.py` and `practicesets/generators/errors.py`, and `model.py` chooses its company from the `PRACTICESET_COMPANY` environment variable **at import time**.

- [ ] **Step 1: Copy the script and write the failing test**

```bash
cp scripts/build_riverbend.py scripts/build_pack.py
```

Create `tests/unit/test_build_pack.py`:

```python
"""The translator's own behaviour, as distinct from any pack it produces.

The script this replaces pointed at a directory that had been refactored away. Its documented
command raised FileNotFoundError and nothing noticed, so the pack it maintains drifted until a
figure had to be corrected by hand. A quiet failure here is the defect, not the symptom.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PRACTICESETS = ROOT.parent / "practicesets"


def _script():
    """scripts/ is not a package, so the module is loaded by path."""
    spec = importlib.util.spec_from_file_location(
        "build_pack", ROOT / "scripts" / "build_pack.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_it_names_what_is_missing_rather_than_failing_obscurely(tmp_path):
    missing = tmp_path / "nowhere"

    with pytest.raises(SystemExit) as caught:
        _script().require_practicesets(missing)

    message = str(caught.value)
    assert str(missing / "generators" / "model.py") in message, message
    assert "Nothing was written" in message, message


@pytest.mark.skipif(not PRACTICESETS.is_dir(), reason="practicesets is not checked out beside us")
def test_it_accepts_the_real_checkout():
    assert _script().require_practicesets(PRACTICESETS).name == "generators"


@pytest.mark.skipif(not PRACTICESETS.is_dir(), reason="practicesets is not checked out beside us")
def test_two_companies_in_one_process_do_not_return_the_same_figures():
    """model.py reads PRACTICESET_COMPANY when it is imported. Without clearing the module
    cache the second company silently returns the first one's model, and every figure in the
    second pack would be wrong while every test still passed."""
    script = _script()
    generators = script.require_practicesets(PRACTICESETS)

    riverbend, _ = script.load_model(generators, "riverbend")
    alderfinch, _ = script.load_model(generators, "alderfinch")

    assert riverbend.SLUG == "Riverbend"
    assert alderfinch.SLUG == "Alder-and-Finch"
    assert len(riverbend.JOURNALS) == 4
    assert len(alderfinch.JOURNALS) == 3
```

- [ ] **Step 2: Run it to watch it fail**

Run: `.venv/bin/python -B -m pytest tests/unit/test_build_pack.py -v -p no:cacheprovider`
Expected: FAIL — `AttributeError: module 'build_pack' has no attribute 'require_practicesets'`.

- [ ] **Step 3: Replace the path resolution and the loader**

In `scripts/build_pack.py`, delete the `DEFAULT_SET` constant (line 30) and the `_load` function (lines 33–46), and put these in their place. Add `import os` to the imports.

```python
DEFAULT_PRACTICESETS = Path(__file__).resolve().parents[2] / "practicesets"


def require_practicesets(path: Path) -> Path:
    """The figures live in a sibling checkout. Say plainly when they are not there.

    The script this replaces resolved a path that had been refactored away and raised
    FileNotFoundError from deep inside an import. It failed that way for long enough that the
    pack it maintains had to be corrected by hand instead of regenerated.
    """
    generators = path / "generators"
    if not (generators / "model.py").is_file():
        raise SystemExit(
            f"The practice sets are not at {path}.\n"
            f"Expected {generators / 'model.py'}, which is where every figure comes from.\n"
            f"Pass --practicesets PATH, or check practicesets out beside this repository.\n"
            f"Nothing was written."
        )
    return generators


def load_model(generators: Path, company: str):
    """Import the practice set's model and errors for one company.

    model.py reads PRACTICESET_COMPANY as it is imported, so the variable is set first and the
    module cache is cleared. Without the clearing, a second company in the same process returns
    the first one's figures and nothing complains.
    """
    os.environ["PRACTICESET_COMPANY"] = company
    if str(generators) not in sys.path:
        sys.path.insert(0, str(generators))

    out = {}
    # The practice set prints a self-check banner when imported; it must not land in the JSON.
    with contextlib.redirect_stdout(io.StringIO()):
        for name in ("model", "errors"):
            sys.modules.pop(name, None)
            spec = importlib.util.spec_from_file_location(name, generators / f"{name}.py")
            mod = importlib.util.module_from_spec(spec)
            sys.modules[name] = mod
            spec.loader.exec_module(mod)
            out[name] = mod
    return out["model"], out["errors"]
```

- [ ] **Step 4: Point `build_source` and the entry point at them**

Change `build_source`'s signature (line 421) from `def build_source(practice_set: Path) -> dict:` to:

```python
def build_source(company: str, practicesets: Path) -> dict:
```

Its first statement becomes:

```python
    generators = require_practicesets(practicesets)
    model, errors_mod = load_model(generators, company)
```

- [ ] **Step 3b: Read the cheques off the model instead of parsing a file**

`_cheques` (lines 201–213) parses `generators/gendocs.py` with `ast` and `literal_eval`s the
module-level `CHK` assignment, to avoid importing a module that would run the whole paper
document build. **That no longer works for any company.** The refactor turned

```python
CHK   = DOCS["cheques"]
```

from a dict literal into a subscript, and `ast.literal_eval` raises
`ValueError: malformed node or string ... Subscript` on it. Verify this for yourself before
changing anything:

```bash
cd ../practicesets && ../originalentry/.venv/bin/python -B -c "
import ast
tree = ast.parse(open('generators/gendocs.py').read())
node = next(n for n in tree.body
            if isinstance(n, ast.Assign) and getattr(n.targets[0], 'id', '') == 'CHK')
ast.literal_eval(node.value)
"
```

The same data is on the model already — `model.DOCS[\"cheques\"]` is a dict of
`{n: (number, payee, memo, amount)}`, 8 entries for Riverbend and 4 for the clinic. Delete
`_cheques` entirely, delete `import ast` from inside it, and replace its call site in
`build_source` (line 463) with:

```python
    cheques = model.DOCS.get("cheques", {})
```

This removes a parser and a side-effect worry at the same time. The reason it was written that
way — importing `gendocs.py` would run the document build — does not apply to `model`, which the
translator has already imported.

- [ ] **Step 3c: Delete the dead trap call**

In `error_signatures` (line 385) delete `wrong_of = {t["no"]: t for t in errors_mod.mutate(variant, "freight")}` and the `_ = wrong_of` at line 417. It is assigned, never read, and names a Riverbend-only trap kind.

Replace the `__main__` block (lines 530–533) with:

```python
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Translate a paper practice set into a pack source.")
    parser.add_argument("company", help="the practicesets company module, e.g. alderfinch")
    parser.add_argument("--practicesets", type=Path, default=DEFAULT_PRACTICESETS,
                        help="path to the practicesets checkout")
    args = parser.parse_args()
    json.dump(build_source(args.company, args.practicesets), sys.stdout,
              indent=1, ensure_ascii=False)
    print()
```

Add `import argparse` to the imports. Update the module docstring to describe the new command and drop the reference to `Riverbend-Paper-Practice-Set`.

- [ ] **Step 5: Run the tests to watch them pass**

Run: `.venv/bin/python -B -m pytest tests/unit/test_build_pack.py -v -p no:cacheprovider`
Expected: 3 passed.

- [ ] **Step 6: Prove the loud failure is load-bearing**

Temporarily change `require_practicesets` to `return generators` unconditionally. Run the test again and confirm `test_it_names_what_is_missing_rather_than_failing_obscurely` FAILS. Restore. Report the failure message you saw. A guard that cannot fail for the reason its name gives is worse than none.

- [ ] **Step 7: Run the whole suite and commit**

Run: `.venv/bin/python -B -m pytest tests/ -q -p no:cacheprovider`

```bash
git add scripts/build_pack.py tests/unit/test_build_pack.py
git commit -m "Make the pack translator run again, and say so when it cannot

It read a directory that was refactored into practicesets/ some time ago, so its documented
command raised FileNotFoundError from inside an import. It failed that way long enough that the
pack it maintains had to be corrected by hand rather than regenerated.

It now takes a company and a path, and a missing checkout stops the run with the file it looked
for. The module cache is cleared between companies: model.py reads PRACTICESET_COMPANY as it is
imported, so without that the second company returns the first one's figures in silence."
```

---

### Task 2: Calibrate against Riverbend, and lock the bridge shut

**Files:**
- Create: `tests/unit/test_pack_reproducible.py`
- Modify: `scripts/build_pack.py` only if the calibration shows a real fault

**Interfaces:**
- Consumes: `build_source(company, practicesets)` from Task 1.

This is the gate. The tool proves itself against the pack already serving students before it is trusted with content nobody can check. **Nothing in Task 3 or later begins until this task's diff is understood.**

- [ ] **Step 1: Regenerate Riverbend and look at the difference**

```bash
.venv/bin/python -B scripts/build_pack.py riverbend > /tmp/riverbend-regenerated.json
.venv/bin/python -B -c "
import json
live = json.load(open('packs/riverbend/source.json'))
new = json.load(open('/tmp/riverbend-regenerated.json'))
print('identical' if live == new else 'DIFFERENT')
print('top-level keys only in one side:', set(live) ^ set(new))
for k in sorted(set(live) & set(new)):
    if live[k] != new[k]:
        print(' differs:', k)
"
```

- [ ] **Step 2: Adjudicate every difference**

For each key reported as differing, find out why and write the finding down. The expected outcome is **no differences at all**: the hand-edit on this branch changed three document strings from `4390.4` to `4,390.40`, and `practicesets/companies/riverbend.py:555` already formats that figure with `{remit:,.2f}`, so a working translator reproduces the corrected text without being told.

Classify each difference as one of:
- **the translator is wrong** — fix `scripts/build_pack.py` and re-run,
- **the live pack drifted** — record it; the regenerated file is correct and becomes the committed one,
- **a deliberate later edit that the model does not carry** — this is the serious case. It means the pack holds content with no upstream, and the finding must be reported rather than papered over.

Do not edit `packs/riverbend/source.json` to make a diff go away. If the regenerated file is right, replace the whole file with it in Step 4 and say so.

- [ ] **Step 3: Write the test that keeps this true**

Create `tests/unit/test_pack_reproducible.py`:

```python
"""The bridge between the paper set and the pack, kept standing.

A translator exists so the figures are authored once. It only delivers that if someone notices
when it stops working. The script this replaces pointed at a directory that had been refactored
away, and the pack it maintains went stale with nothing watching, until a money figure had to be
corrected by editing the JSON three times by hand.

This test is the thing that was missing.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PRACTICESETS = ROOT.parent / "practicesets"
LIVE = ROOT / "packs" / "riverbend" / "source.json"

pytestmark = pytest.mark.skipif(
    not PRACTICESETS.is_dir(), reason="practicesets is not checked out beside us")


def _build(company):
    spec = importlib.util.spec_from_file_location(
        "build_pack", ROOT / "scripts" / "build_pack.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build_source(company, PRACTICESETS)


def test_regenerating_riverbend_reproduces_the_pack_in_service():
    """If this fails, either the translator broke or the committed pack has content that no
    longer traces to the practice set. Both are worth stopping for."""
    assert _build("riverbend") == json.loads(LIVE.read_text())


def test_the_corrected_money_figure_comes_from_the_model():
    """The sharpest single test that the bridge works: this text was once patched into the JSON
    by hand, three times. The model has formatted it correctly for longer than the patch has
    existed, so a working translator emits it unprompted."""
    text = json.dumps(_build("riverbend"))

    assert "4,390.40" in text
    assert "4390.4" not in text
```

- [ ] **Step 4: Run it**

Run: `.venv/bin/python -B -m pytest tests/unit/test_pack_reproducible.py -v -p no:cacheprovider`
Expected: 2 passed. If `test_regenerating_riverbend_reproduces_the_pack_in_service` fails, Step 2 is not finished — go back to it rather than loosening the assertion.

- [ ] **Step 5: Prove the reproducibility test is load-bearing**

Temporarily change one account name in `packs/riverbend/source.json`, run the test, confirm it FAILS, and restore the file with `git checkout -- packs/riverbend/source.json`. Report the failure.

- [ ] **Step 6: Confirm the live pack's figures are untouched**

Run: `.venv/bin/python -B -m pytest tests/unit/test_riverbend_pack.py -v -p no:cacheprovider`
Expected: all pass. This guards the pack's figures against the printed solution set for all three versions; it must not have moved.

- [ ] **Step 7: Commit**

```bash
git add tests/unit/test_pack_reproducible.py packs/riverbend/source.json
git commit -m "Prove the translator against the pack already in service

Regenerating Riverbend now reproduces the source.json students work against, so the translator
can be trusted with a company whose output nobody can check by eye.

The test that asserts it is the one that was missing. A bridge only delivers authored-once if
somebody notices when it falls down, and this one was down for an unknown length of time."
```

---

### Task 3: Move everything company-specific into a profile

**Files:**
- Create: `packs/riverbend/profile.py`
- Modify: `scripts/build_pack.py`
- Delete: `scripts/build_riverbend.py`

**Interfaces:**
- Produces: a profile module exposing `COMPANY: dict`, `PERIOD: dict`, `STATEMENT_SECTIONS: list[str]`, `NON_CURRENT: set[str]`, `ROLES: dict[str, list[str]]`, `SUBSIDIARY: dict[str, str]`, `JOURNAL_OF: dict[str, str]`, `JOURNALS: list[dict]`, `NO_ENTRY_DOCUMENTS: list[dict]`, `CHECKPOINTS: list[dict]`, `RUBRIC: list[dict]`.
- Produces: `load_profile(slug: str) -> ModuleType` in `scripts/build_pack.py`.

Task 2's reproducibility test is the safety net for this whole task: the output must not change by one byte.

- [ ] **Step 1: Create the profile by moving, not retyping**

Create `packs/riverbend/profile.py` with this header, then move the named definitions out of `scripts/build_pack.py` **verbatim** — do not retype them, and do not improve them:

```python
"""What is true of Riverbend rather than of packs in general.

The translator is machinery and knows no company. Everything here is one company's shape: which
accounts are non-current, which cycle goes in which journal, what the checkpoints ask for, and
the documents that start no entry at all.

Moved out of the translator unchanged. tests/unit/test_pack_reproducible.py is what proves the
move altered nothing.
"""

from __future__ import annotations
```

Move these, keeping their names and contents exactly:
- `NON_CURRENT` (line 64), `ROLES` (65–66), `SUBSIDIARY` (67), `JOURNAL_OF` (70–71) and its comment
- the whole `journals()` function (74–120) — rename it to nothing; assign its return value to `JOURNALS` by calling it at the bottom of the profile: `JOURNALS = _journals()`, renaming `def journals()` to `def _journals()`
- `NO_ENTRY_DOCUMENTS` (166–193)
- From `build_source` (lines 486–525): the `company` dict becomes `COMPANY`; `period` becomes `PERIOD`; `statement_sections` becomes `STATEMENT_SECTIONS`; the `checkpoints` list becomes `CHECKPOINTS`; the `rubric` components list becomes `RUBRIC`.

`TYPE`, `DEBIT_NORMAL` and `SECTION` (lines 54–63) stay in the translator — they are keyed by account type, not by account number, and are the same for every company.

- [ ] **Step 2: Teach the translator to load a profile**

Add to `scripts/build_pack.py`:

```python
def load_profile(slug: str):
    """The pack's own shape, which lives beside the pack it describes."""
    path = Path(__file__).resolve().parents[1] / "packs" / slug / "profile.py"
    if not path.is_file():
        raise SystemExit(
            f"No profile for {slug!r}.\n"
            f"Expected {path}, which declares the journals, checkpoints and rubric.\n"
            f"Nothing was written."
        )
    spec = importlib.util.spec_from_file_location(f"{slug}_profile", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
```

The practicesets company module and the pack slug are different strings (`riverbend` the module, `riverbend` the slug here, but `alderfinch` the module against `alderfinch` the slug). Take both on the command line rather than guessing one from the other: add `--slug` defaulting to the company name.

`build_source` becomes:

```python
def build_source(company: str, practicesets: Path, slug: str | None = None) -> dict:
    generators = require_practicesets(practicesets)
    model, errors_mod = load_model(generators, company)
    profile = load_profile(slug or company)
```

Then replace every use of the moved names with `profile.NAME`: `JOURNAL_OF[...]` becomes `profile.JOURNAL_OF[...]`, `journals()` becomes `profile.JOURNALS`, `NO_ENTRY_DOCUMENTS` becomes `profile.NO_ENTRY_DOCUMENTS`, and the five literal blocks in the returned dict become `profile.COMPANY`, `profile.PERIOD`, `profile.STATEMENT_SECTIONS`, `profile.CHECKPOINTS` and `{"components": profile.RUBRIC}`. `NON_CURRENT`, `ROLES` and `SUBSIDIARY` are used by the account-building code; pass `profile` into whatever helper needs them rather than reaching for a global.

Update `tests/unit/test_pack_reproducible.py`'s `_build` to call `module.build_source(company, PRACTICESETS)` unchanged — the slug defaults to the company name, so Riverbend needs no argument.

- [ ] **Step 3: Prove the move changed nothing**

Run: `.venv/bin/python -B -m pytest tests/unit/test_pack_reproducible.py tests/unit/test_riverbend_pack.py -v -p no:cacheprovider`
Expected: all pass. A failure here means the move was not verbatim. Find the difference rather than adjusting the expectation.

- [ ] **Step 4: Delete the script this replaces**

```bash
git rm scripts/build_riverbend.py
```

Then grep for references and fix them: `grep -rn "build_riverbend" --include="*.py" --include="*.md" . | grep -v .venv`. `tests/unit/test_riverbend_pack.py`'s docstring names it and must be updated to `scripts/build_pack.py`.

- [ ] **Step 5: Run the whole suite and commit**

Run: `.venv/bin/python -B -m pytest tests/ -q -p no:cacheprovider`

```bash
git add -A
git commit -m "Move one company's shape out of the machinery

The translator carried Riverbend's journals, its non-current accounts, its checkpoints, its
rubric and its triage distractors as literals. A second company could not be expressed without
editing the script that serves the first.

Everything moved verbatim and the output is unchanged to the byte, which the reproducibility
test is what proves. The old entry point is gone rather than left to rot a second time."
```

---

### Task 4: Move the content helpers that would quietly lie about a clinic

**Files:**
- Modify: `scripts/build_pack.py`, `packs/riverbend/profile.py`

**Interfaces:**
- Consumes: the profile module from Task 3.
- Produces: four more names every profile must declare, which Task 5's clinic profile relies on —
  `REFERENCE_PAGES: list[dict]` with keys `key`, `title`, `builder` where `builder(model) -> dict`;
  `EXTRA_PARTIES: list[dict]` (default `[]`); `FACE_ACCOUNTS: dict[str, str]` with keys `cash`,
  `receivable`, `payable`; `SPECIAL_DOCUMENTS: dict[str, int]`; and `check(model) -> None`,
  which `build_source` calls immediately after loading the profile.

Task 3 moved the declarations. These are the helpers that *compute* content and would produce a
plausible, wrong pack for a company that is not Riverbend. None of them crashes; all of them lie,
which is worse. Task 2's reproducibility test is the net for all of it — the output must stay
identical to the byte.

- [ ] **Step 1: The reference pages**

`reference(model)` (lines 121–160) builds an "Inventory and costs" page from `model.SKUS` and
writes the sentence *"Riverbend keeps a perpetual inventory."* The clinic has a `SKUS` dict, so
this does not crash — it emits a priced inventory page for a business holding no inventory, whose
"stock" is `('Consultation, standard', 0, None, 0, False)`.

Move the page-building into the profile as `REFERENCE_PAGES`, a list of
`{"key", "title", "builder"}` where `builder` is a function taking `model` and returning the
blocks. Riverbend keeps both its pages; the translator just calls what the profile gives it:

```python
    "reference": [page["builder"](model) for page in profile.REFERENCE_PAGES],
```

The clinic's profile will declare only a payroll page, written in Task 5.

- [ ] **Step 2: The invented vendor**

Lines 444–448 append a literal party to every pack:

```python
        + [{"code": "V-206", "kind": "supplier", "name": "Kestrel Office Supply"}]
```

and line 459 gives it an opening balance of `{"V-206": 0}`. This is a Riverbend patch. Left in
place it puts a vendor in the clinic's subsidiary ledger that the clinic never traded with, and
a student reconciling the A/P control would find a name with no history. Move it to the profile
as `EXTRA_PARTIES: list[dict]`, defaulting to `[]`, and have the translator add their zero
openings from that list rather than from a literal.

- [ ] **Step 3: The date, the base variant and the face amount**

- `_iso_date` (346–349) returns `f"2026-12-{day:02d}"`. Take the year and month from
  `profile.PERIOD["start"]` instead of the literal.
- `documents()` (line 316) calls `model.build("B")`. Use `sorted(model.VARIANTS)[0]`, so a set
  whose versions are not lettered A/B/C still works, and assert the chosen code is in
  `model.VARIANTS` so a missing variant fails loudly.
- `_face_amount` (216–232) hardcodes accounts 101, 105 and 201 to decide what a document is for.
  Take them from the profile: add `FACE_ACCOUNTS = {"cash": "101", "receivable": "105",
  "payable": "201"}` and read it there. The clinic happens to use the same three numbers, which
  is exactly why leaving them as literals would go unnoticed until a company that does not.

- [ ] **Step 4: The special-cased transactions**

`_text_alternative` (239–305) hardcodes transaction numbers 18, 24, 25, 26 and 27 to attach
payroll, discount and petty-cash detail. Riverbend has 28 transactions; **the clinic has 15**, so
every one of those branches is dead for it and the documents lose detail with nothing reporting
it.

Move the numbers to the profile as `SPECIAL_DOCUMENTS = {"payroll": 24, "discount": 25, ...}`,
keyed by what each one is rather than by its number, and have the helper look them up. In the
profile, assert the set is a subset of the transaction numbers actually present, so a number that
stops existing is a failure rather than a silence:

```python
def check(model):
    """A special-cased number that no longer exists must fail, not quietly do nothing."""
    numbers = {t["no"] for t in model.build(sorted(model.VARIANTS)[0])}
    missing = set(SPECIAL_DOCUMENTS.values()) - numbers
    if missing:
        raise SystemExit(f"{COMPANY['slug']}: no transaction numbered {sorted(missing)}.")
```

Call `profile.check(model)` from `build_source` immediately after loading the profile.

- [ ] **Step 5: Prove nothing moved**

Run: `.venv/bin/python -B -m pytest tests/unit/test_pack_reproducible.py tests/unit/test_riverbend_pack.py -v -p no:cacheprovider`
Expected: all pass. The output must be byte-identical; a difference means a move was not verbatim.

- [ ] **Step 6: Prove the new guard bites**

Temporarily change one value in `packs/riverbend/profile.py`'s `SPECIAL_DOCUMENTS` to `99`, run
the suite, and confirm it fails with the message naming 99. Restore. Report what you saw.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Move the helpers that would quietly lie about another company

None of these crash for a veterinary clinic. The inventory reference page prints for a business
holding none, a vendor Riverbend once needed appears in the clinic's subsidiary ledger with no
history behind it, and five transaction numbers special-cased for a 28-transaction set are
simply dead in a 15-transaction one, taking their document detail with them.

A pack that crashes gets fixed. A pack that is plausible and wrong gets marked."
```

---

### Task 5: Write the clinic's profile and generate its source

**Files:**
- Create: `packs/alderfinch/profile.py`
- Create: `packs/alderfinch/source.json` (generated)

**Interfaces:**
- Consumes: `load_profile`, `build_source` from Task 3.

What makes this company different, established by reading its model:

- **Three journals**: `fees`, `cash_receipts`, `cash_payments`. No Purchases Journal and no COGS or inventory column anywhere; `ACC["INVENTORY"]` and `ACC["COGS"]` are both `None`.
- **Its transactions still carry a `Purchases` cycle** — two of them, supplies bought on account (Dr 115 Clinic Supplies, Cr 201 Accounts Payable). With no Purchases Journal they belong in the General Journal, which is what the paper books instruct: "Use the General Journal only when no special journal fits." `JOURNAL_OF` must map `"Purchases"` to `"general"`.
- **Period is 1–7 December**, not 1–15.
- **Non-current accounts are `150` and `151` only**; the clinic has no `155`/`156`.
- 35 accounts, 5 clients, 3 vendors, 15 transactions.

- [ ] **Step 1: Write the profile**

Create `packs/alderfinch/profile.py`:

```python
"""What is true of Alder & Finch rather than of packs in general.

A service practice: fees charged on account, no inventory and no cost of sales. Three special
journals instead of four, so a purchase of supplies on account has no special journal to go in
and belongs in the General Journal, which is what the paper books tell the student.
"""

from __future__ import annotations

COMPANY = {
    "slug": "alderfinch",
    "name": "Alder & Finch Veterinary Clinic",
    "accent_hex": "#2F6F4E",
    "monogram": "AF",
    "course_tags": ["ACCT1010"],
    "scope_tags": ["service business", "special journals", "subsidiary ledgers"],
}

PERIOD = {"start": "2026-12-01", "end": "2026-12-07", "fiscal_year_end": "2026-12-31"}

STATEMENT_SECTIONS = ["current_assets", "non_current_assets", "current_liabilities",
                      "non_current_liabilities", "equity", "sales_revenue",
                      "operating_expenses"]

NON_CURRENT = {"150", "151"}
ROLES = {"302": ["retained_earnings"], "399": ["income_summary"],
         "105": ["ar_control"], "201": ["ap_control"]}
SUBSIDIARY = {"105": "customer", "201": "supplier"}

# The clinic has no Purchases Journal, so a purchase on account goes where the paper books send
# it: "Use the General Journal only when no special journal fits."
JOURNAL_OF = {"Fees": "fees", "Purchases": "general", "Cash receipts": "cash_receipts",
              "Cash payments": "cash_payments", "General": "general"}


def _col(key, label, side, account, posts="total", subsidiary=None):
    """Column shape copied from Riverbend's profile. `posts` is required: a named column posts
    its total to one account, an "Other accounts" column posts its lines individually."""
    c = {"key": key, "label": label, "side": side, "posts": posts}
    if account is not None:
        c["account"] = account
    if subsidiary:
        c["subsidiary_kind"] = subsidiary
    return c


# Every special journal carries an "Other accounts" column (account: None, posts individually).
# That is how a real special journal takes the entries its named columns do not cover, and
# Riverbend's profile says plainly why it is not optional: without it V8 refuses the rent cheque
# and the payroll. The clinic pays rent and a payroll too.
JOURNALS = [
    {"key": "fees", "name": "Fees Journal", "ref_prefix": "F", "kind": "special",
     "columns": [
         _col("ar_dr", "Accounts Receivable Dr", "debit", "105", subsidiary="customer"),
         _col("fees_cr", "Fees Earned Cr", "credit", "401")]},
    {"key": "cash_receipts", "name": "Cash Receipts Journal", "ref_prefix": "CR",
     "kind": "special", "columns": [
         _col("cash_dr", "Cash Dr", "debit", "101"),
         _col("disc_dr", "Fee Discounts Dr", "debit", "403"),
         _col("ar_cr", "Accounts Receivable Cr", "credit", "105", subsidiary="customer"),
         _col("fees_cr", "Fees Earned Cr", "credit", "401"),
         _col("other_cr", "Other accounts Cr", "credit", None, posts="individual")]},
    {"key": "cash_payments", "name": "Cash Payments Journal", "ref_prefix": "CP",
     "kind": "special", "columns": [
         _col("ap_dr", "Accounts Payable Dr", "debit", "201", subsidiary="supplier"),
         _col("other_dr", "Other accounts Dr", "debit", None, posts="individual"),
         _col("cash_cr", "Cash Cr", "credit", "101")]},
    # No "columns" key at all, exactly as Riverbend's general journal is written.
    {"key": "general", "name": "General Journal", "ref_prefix": "J", "kind": "general"},
]

# Checkpoint 3 is deliberately not the Accounts Payable control. The clinic's A/P closes at
# 6,040.00 in all three versions, so it could be copied between students without being worked.
# Unearned Boarding Revenue differs in every version and is the distinction the set is built to
# teach: money taken for work not yet done is not a fee.
CHECKPOINTS = [
    {"key": "cp1", "ordinal": 1, "stage": "posted",
     "prompt": "Accounts Receivable control balance at 7 December",
     "measure": {"account": "105"}},
    {"key": "cp2", "ordinal": 2, "stage": "posted",
     "prompt": "Cash balance at 7 December", "measure": {"account": "101"}},
    {"key": "cp3", "ordinal": 3, "stage": "posted",
     "prompt": "Unearned Boarding Revenue balance at 7 December",
     "measure": {"account": "215"}},
]

RUBRIC = [
    {"key": "triage", "points": 10},
    {"key": "journal_selection", "points": 20},
    {"key": "entry_accuracy", "points": 40},
    {"key": "posting_completeness", "points": 20},
    {"key": "subsidiary_agreement", "points": 10},
]

# Riverbend patches in a vendor it needed; the clinic trades with nobody extra.
EXTRA_PARTIES = []

FACE_ACCOUNTS = {"cash": "101", "receivable": "105", "payable": "201"}

# Riverbend special-cases five transaction numbers to attach payroll, discount and petty-cash
# detail. The clinic has fifteen transactions, a payroll and its employer tax, and no petty cash
# or settlement discount at all. check() below is what turns a number that stops existing into a
# failure instead of a document quietly missing its detail.
SPECIAL_DOCUMENTS = {"payroll": 13, "employer_tax": 15}


def _payroll_page(model):
    """The clinic's only reference page. It holds no inventory, so Riverbend's 'Inventory and
    costs' page has no counterpart here — printing one would describe a business this is not."""
    pr = model.PR
    rate = pr["fica_rate"]
    return {
        "key": "payroll",
        "title": "Payroll",
        "blocks": [
            {"type": "p", "text": "Staff are paid weekly. The employer owes the same FICA as the "
                                  "employee, which is a separate entry from the wages."},
            {"type": "table",
             "rows": [["Clinical salaries", f"{pr['sales_sal']:,.2f}"],
                      ["Office salaries", f"{pr['office_sal']:,.2f}"],
                      ["FICA rate", f"{rate * 100:.2f}%"],
                      ["Federal withholding", f"{pr['fed_wh']:,.2f}"],
                      ["State withholding", f"{pr['st_wh']:,.2f}"]]},
        ],
    }


REFERENCE_PAGES = [{"key": "payroll", "title": "Payroll", "builder": _payroll_page}]


def check(model):
    """A special-cased number that no longer exists must fail, not quietly do nothing."""
    numbers = {t["no"] for t in model.build(sorted(model.VARIANTS)[0])}
    missing = set(SPECIAL_DOCUMENTS.values()) - numbers
    if missing:
        raise SystemExit(f"{COMPANY['slug']}: no transaction numbered {sorted(missing)}.")


NO_ENTRY_DOCUMENTS = []
```

Two notes for the implementer:

- `NO_ENTRY_DOCUMENTS` is empty here and Step 3 fills it.
- The Fee Discounts column (`403`) is in the Cash Receipts Journal, but no clinic transaction
  takes a settlement discount — both remittances pay in full. Riverbend's journals carry "the
  columns the transactions actually use". Check whether V8 or the journal UI objects to a column
  nothing posts to. If it does not, keep the column: a real fees journal has one, and its absence
  would tell a student that discounts cannot happen. Report which way it went.

- [ ] **Step 2: Generate and read the result**

```bash
mkdir -p packs/alderfinch
.venv/bin/python -B scripts/build_pack.py alderfinch > packs/alderfinch/source.json
.venv/bin/python -B -c "
import json; d=json.load(open('packs/alderfinch/source.json'))
for k,v in d.items():
    print(f'{k:20}', type(v).__name__, len(v) if isinstance(v,(list,dict)) else v)
print()
print('journals :', [j['key'] for j in d['journals']])
print('documents:', len(d['documents']))
print('triage true/false per variant:')
for code,a in d['answers'].items():
    t=a['triage']; print('  ',code, sum(1 for x in t.values() if x), 'entered,',
                         sum(1 for x in t.values() if not x), 'quiet')
"
```

Expected: 3 journals plus `general`, 15 documents, and every triage value `True` because `NO_ENTRY_DOCUMENTS` is empty.

- [ ] **Step 3: Decide the triage distractors**

Rule V10 requires every variant's answer key to carry a triage value for every document, and the `triage` grading component is worth 10 points. With no document that starts no entry, triage is not a judgement — every answer is yes, and a student who never thinks about it scores full marks.

Riverbend ships three distractors — a purchase order, a request for quotation and a price list —
dated at the period end, none of which is a transaction. Use these two for the clinic, which are
documents a veterinary practice really receives and which record no accounting event. The dates
sit inside 1–7 December, not Riverbend's 15 December:

```python
NO_ENTRY_DOCUMENTS = [
    {
        "ref": "N01", "display_ref": "Quotation CV-Q-0118", "date": "2026-12-07",
        "fields": [["From", "Cedarline Veterinary Supply"], ["Quotation", "CV-Q-0118"],
                   ["Valid until", "31 January"], ["Terms", "2/10, n/30"],
                   ["Description", "Price held for a digital dental radiography unit, "
                                   "no order placed"],
                   ["Amount", "6,400.00"]],
        "lines": [["1", "Digital dental radiography unit", "6,400.00", "6,400.00"]],
    },
    {
        "ref": "N02", "display_ref": "Boarding enquiry BK-2209", "date": "2026-12-07",
        "fields": [["From", "Harborview Kennels"], ["Reference", "BK-2209"],
                   ["Dates enquired", "12 to 19 February"],
                   ["Description", "Asks whether twelve runs can be held; no booking made and "
                                   "no deposit taken"],
                   ["Amount", "—"]],
        "lines": [],
    },
]
```

The second is deliberately close to transaction 9, where Harborview Kennels *does* pay 900 in
advance and that deposit is a real entry. A student who records the enquiry has not distinguished
a booking from an enquiry, which is the judgement the triage marks are for. A distractor that is
obviously not a transaction tests nothing.

Regenerate and confirm each variant now reports 15 entered and 2 quiet.

- [ ] **Step 4: Commit**

```bash
git add packs/alderfinch/profile.py packs/alderfinch/source.json
git commit -m "Describe the clinic, and generate its pack source

A service practice: fees on account, no inventory, no cost of sales, three special journals
instead of four. Its two purchases of supplies on account have no special journal to go in, so
they go where the paper books send them, to the General Journal.

Checkpoint 3 is not the Accounts Payable control. The clinic's A/P closes at the same figure in
all three versions, so that checkpoint could be passed by copying. Unearned Boarding Revenue
differs in every version and is the distinction the set exists to teach."
```

---

### Task 6: Build it, validate it, and guard its figures against the paper key

**Files:**
- Create: `tests/unit/test_alderfinch_pack.py`

**Interfaces:**
- Consumes: `packs/alderfinch/source.json` from Task 5.

The figures below were computed from the practicesets model with its own `trial_balance`, the same function the printed solution set uses for its Checkpoint Answers page. They are the authority. **If the app disagrees with them, the app's figures are wrong — do not edit this table to match the code.**

| Version | Cash (101) | A/R control (105) | Unearned Boarding (215) |
| --- | --- | --- | --- |
| A | 33,943.75 | 7,700.00 | 3,210.00 |
| B | 34,043.75 | 7,710.00 | 3,300.00 |
| C | 34,143.75 | 7,720.00 | 3,390.00 |

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_alderfinch_pack.py`:

```python
"""The clinic: Alder & Finch Veterinary Clinic, 1-7 December.

The paper practice set is the source of truth and scripts/build_pack.py only translates it. What
this guards is that the translation stayed faithful: the figures the app derives by replaying the
key through its own ledger engine must equal the figures in the paper solution, to the cent, for
all three versions.

If those ever disagree, a student marked by this app and a student marked from the printed key
would receive different marks for the same work.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from originalentry.generator import build
from originalentry.packs.validate import validate_pack, warn_pack

SOURCE = Path(__file__).resolve().parents[2] / "packs" / "alderfinch" / "source.json"

# Computed from the practicesets model with its own trial_balance, which is what prints the
# solution set's Checkpoint Answers page.
PAPER = {
    "A": {"cp1": Decimal("7700.00"), "cp2": Decimal("33943.75"), "cp3": Decimal("3210.00")},
    "B": {"cp1": Decimal("7710.00"), "cp2": Decimal("34043.75"), "cp3": Decimal("3300.00")},
    "C": {"cp1": Decimal("7720.00"), "cp2": Decimal("34143.75"), "cp3": Decimal("3390.00")},
}


def _built():
    return build.build(json.loads(SOURCE.read_text()))


def test_the_pack_passes_every_rule():
    generated = _built()

    assert validate_pack(generated.pack) == []


def test_the_checkpoints_match_the_paper_solution():
    generated = _built()

    for code, expected in PAPER.items():
        checkpoints = generated.keys[code]["checkpoints"]
        for key, figure in expected.items():
            assert Decimal(checkpoints[key]) / 100 == figure, f"{code} {key}"


def test_no_checkpoint_can_be_passed_by_copying():
    """Three versions exist to make copying visible. A checkpoint that answers the same in all
    three cannot do that, and the clinic's Accounts Payable control is exactly such a figure."""
    generated = _built()

    for key in ("cp1", "cp2", "cp3"):
        answers = {generated.keys[code]["checkpoints"][key] for code in ("A", "B", "C")}
        assert len(answers) == 3, f"{key} answers the same in more than one version"


def test_a_credit_balance_checkpoint_is_asked_as_a_positive_figure():
    """Unearned Boarding Revenue is a liability and is stored with a negative sign. A student
    reads the balance off a trial balance's credit column and writes it as a positive number;
    asking them for a negative one is a question about this app, not about accounting."""
    generated = _built()

    for code in ("A", "B", "C"):
        assert generated.keys[code]["checkpoints"]["cp3"] > 0


def test_the_pack_warns_about_nothing():
    generated = _built()

    assert warn_pack(generated.pack) == []
```

- [ ] **Step 2: Run it to watch it fail**

Run: `.venv/bin/python -B -m pytest tests/unit/test_alderfinch_pack.py -v -p no:cacheprovider`

Expected: failures. Work them one at a time and report each. The likely ones, and what each means:
- **V8** — an entry posts to an account its journal has no column for. Either `JOURNAL_OF` sends a transaction to the wrong journal, or a column is missing from the profile. This is the rule that tests the three-journal shape.
- **V5** — more or less than one control account for a party kind. Check `ROLES` and `SUBSIDIARY` in the profile.
- **V9** — replaying the key does not reproduce the balances. This is the serious one: it means the translated entries do not say what the model says. Report it rather than adjusting anything.
- **V3** — a reference to an account or party that does not exist.

If a checkpoint figure disagrees with the table, the table wins. Find out why the app's figure differs.

- [ ] **Step 3: Build the pack zip**

```bash
.venv/bin/python -B scripts/generate_pack.py packs/alderfinch/source.json /tmp/alderfinch.zip --paper
.venv/bin/python -B -m flask packs validate /tmp/alderfinch.zip
```

Expected: the generator prints the pack and `packs validate` reports no problems. `--paper` skips image rendering; images are not needed to prove the content.

- [ ] **Step 4: Run the whole suite**

Run: `.venv/bin/python -B -m pytest tests/ -q -p no:cacheprovider`
Expected: everything passes, including `test_riverbend_pack.py` and `test_pack_reproducible.py` unchanged.

- [ ] **Step 5: Prove the anti-copying test is load-bearing**

Temporarily change `cp3`'s `measure.account` in `packs/alderfinch/profile.py` to `"201"` (the Accounts Payable control), regenerate the source, and run `test_no_checkpoint_can_be_passed_by_copying`. Confirm it FAILS with cp3 named. Restore the profile and regenerate. Report the failure message.

- [ ] **Step 6: Commit**

```bash
git add tests/unit/test_alderfinch_pack.py packs/alderfinch/source.json
git commit -m "Guard the clinic's figures against the printed key

The app derives its figures by replaying the key through its own ledger engine. The paper set
computes them with its own trial balance. If those two ever disagree, a student marked on screen
and a student marked from the printed solution get different marks for the same work.

A checkpoint that answers the same in all three versions is also tested for, because three
versions exist to make copying visible and a checkpoint that cannot do that is decoration."
```

---

## Before this reaches a student

Everything above is internal consistency, and internal consistency is also what a confident
mistake looks like. Two things remain that no test can do:

- **Someone works a version through the browser as a student**, from the first document to the
  third checkpoint, without looking at the key. The clinic is the first service business and the
  first three-journal pack this app has ever served; the journal-selection screen has never been
  seen with a Fees Journal on it.
- **The two triage distractors written in Task 5 Step 3 are read by someone who teaches this**,
  since a distractor that is obviously not a transaction teaches nothing and one that is
  arguably a transaction is unfair.

## Not in this plan

- **Thorne & Meadow.** A full month carrying six adjustments; it would be the first pack to
  exercise the adjustment rules, the adjustment grading components and probably statements and
  closing. It deserves its own design rather than being appended here.
- Document images. `--paper` skips them; the clinic's pack ships without them until the content
  is proven.
- The hardcoded Riverbend path in `flask seed demo` (`cli.py:256-277`).
- Any change to the practicesets repository.
