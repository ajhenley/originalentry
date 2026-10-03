# No Transaction List Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the online pack telling a student what each transaction was, and move the reason a document needs no entry out of the student's view and into the answer key.

**Architecture:** The reason a document needs no entry becomes `AnswerKey.triage_reasons`, authored once per ref in each profile's `FILED_REASONS` and copied into every version's key. A new validation rule V17 makes a missing reason impossible. Once the reason has that home, the `Description` row — written onto 28 Riverbend documents from `txn["desc"]` and authored literally onto 3 more — is deleted, and the instructor walkthrough reads the key instead of the document.

**Tech Stack:** Python 3.14, Flask 3.1, Pydantic v2 (`originalentry/packs/schema.py`), pytest. No JavaScript anywhere. Packs are JSON (`packs/<slug>/source.json`) built by `scripts/build_pack.py` from a read-only sibling repo `../practicesets`.

**Spec:** `docs/superpowers/specs/2026-10-02-no-transaction-list-design.md` — read it before Task 1. It carries the evidence for every change here and the list of what this work deliberately does not fix.

## Global Constraints

- **Interpreter.** This worktree has no `.venv`, and `pip install` is broken on this machine until `brew upgrade python@3.14` fixes a `pyexpat` mismatch. Use `/Volumes/Nevvie/Library/Dropbox/habichuela123/originalentry/.venv/bin/python`. Before trusting any test result, confirm it resolves imports to *this* worktree:
  `$PY -c "import originalentry; print(originalentry.__file__)"` must print a path containing `originalentry-prose`. A venv resolving to the other checkout would run every test against the wrong tree and pass.
- **Always** run Python as `$PY -B` and pytest with `-p no:cacheprovider`. Stale `__pycache__` has already made a failing test on this project look like a passing one.
- `pytest-timeout` is **not** installed. Do not pass `--timeout`.
- **Do not run the full suite.** It takes about an hour against a shared Neon Postgres, and two concurrent runs against it deadlock. Run the modules you touch. Task 5 runs the suite once.
- **Never run `flask packs import`.** It writes to a shared live Postgres with students in it. `flask packs validate` is fine.
- **Do not modify `../practicesets`.** Read-only from here.
- **Never use `git stash`** — the stack is shared with other worktrees and other sessions. Use a WIP commit.
- **No JavaScript.** Guarded by `tests/guards/test_javascript.py`.
- `ruff check originalentry tests scripts` must be clean at every commit.
- **Riverbend is a live pack with students in it.** Its checkpoint figures, expected entries, expected balances, rubric and document count must not change. Task 4 proves it.
- House style for a refusal: a sentence saying what is wrong and what to do, ending `Nothing was written.`

---

## File Structure

| File | Responsibility | Task |
| --- | --- | --- |
| `originalentry/packs/schema.py` | `AnswerKey.triage_reasons: dict[str, str]` | 1 |
| `originalentry/generator/build.py` | pass `triage_reasons` through `_build_key`'s whitelist | 1 |
| `scripts/build_pack.py` | write `triage_reasons` from `profile.FILED_REASONS` in both answer arms; later, stop writing `Description` | 1, 4 |
| `packs/riverbend/profile.py` | `FILED_REASONS` for N01–N03; later, drop their authored `Description` rows | 1, 4 |
| `packs/alderfinch/profile.py` | `FILED_REASONS` for the 11 filed documents | 1 |
| `originalentry/packs/validate.py` | V17, both halves | 2 |
| `scripts/build_walkthrough.py` | read the reason from the key, not the document | 3 |
| `tests/unit/test_triage_reasons.py` (new) | the field end to end, and V17 | 1, 2 |
| `tests/unit/test_no_transaction_list.py` (new) | no document in either pack carries `Description`; the trap phrases are gone | 4 |
| `tests/unit/test_riverbend_pack.py` | invert the assertion that required `Description` | 4 |
| `tests/unit/test_alderfinch_pack.py` | the clinic's instructor copy builds again; the refusal still fires for a pack that lacks a reason | 3 |
| `packs/*/source.json` | regenerated output | 1, 4 |

---

### Task 1: The reason gets a home in the answer key

**Files:**
- Modify: `originalentry/packs/schema.py` (class `AnswerKey`, around line 213)
- Modify: `originalentry/generator/build.py:116-124` (`_build_key`'s field whitelist)
- Modify: `scripts/build_pack.py:959` and `scripts/build_pack.py:990` (the two answer arms)
- Modify: `packs/riverbend/profile.py` (add `FILED_REASONS`)
- Modify: `packs/alderfinch/profile.py` (add `FILED_REASONS`)
- Regenerate: `packs/riverbend/source.json`, `packs/alderfinch/source.json`
- Test: `tests/unit/test_triage_reasons.py` (new)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `AnswerKey.triage_reasons: dict[str, str]`, mapping a document `ref` to the sentence saying why it needs no entry. Present in every version's key. Populated from `profile.FILED_REASONS: dict[str, str]`, which is authored once per ref, **not** per version. Task 2 validates it; Task 3 reads it.

In this task Riverbend's three sentences exist in two places at once — the authored `Description` row and `triage_reasons`. That duplication is deliberate and temporary: it keeps the walkthrough working until Task 3 switches it over, and Task 4 deletes the row. Do not delete the `Description` rows in this task.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_triage_reasons.py`:

```python
"""Why a document needs no entry belongs with the answer, not on the document.

Riverbend printed the sentence in the text a student reads, which told them the triage answer
to three of its ten triage marks. The clinic, taking its documents from the printed envelope,
had nowhere to put the sentence at all, so its instructor copy printed "no entry required"
above a blank line eleven times.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from originalentry.generator import build

ROOT = Path(__file__).resolve().parents[2]
PACKS = ("riverbend", "alderfinch")


@pytest.fixture(scope="module", params=PACKS)
def pack(request):
    source = json.loads((ROOT / "packs" / request.param / "source.json").read_text())
    return request.param, source, build(source, render_images=False)


def test_every_filed_document_has_a_reason_in_every_version(pack):
    slug, source, generated = pack

    for code, key in generated.keys.items():
        filed = [ref for ref, needs_entry in key["triage"].items() if not needs_entry]
        assert filed, f"{slug} version {code} files nothing, so this test proves nothing"
        for ref in filed:
            reason = key["triage_reasons"].get(ref, "")
            assert reason.strip(), f"{slug} {code}: {ref} needs no entry and says no why"


def test_no_reason_is_recorded_for_a_document_that_takes_an_entry(pack):
    """A reason left behind on a document that later takes an entry is how a correct note
    becomes a wrong one."""
    slug, source, generated = pack

    for code, key in generated.keys.items():
        entered = [ref for ref, needs_entry in key["triage"].items() if needs_entry]
        stray = [ref for ref in entered if ref in key["triage_reasons"]]
        assert not stray, f"{slug} {code}: {stray} take an entry and carry a no-entry reason"


def test_the_reason_is_authored_once_and_not_per_version(pack):
    """One sentence per ref in the profile, copied into each version. Three divergent copies
    would be three places to correct."""
    slug, source, generated = pack

    by_ref: dict[str, set[str]] = {}
    for key in generated.keys.values():
        for ref, reason in key["triage_reasons"].items():
            by_ref.setdefault(ref, set()).add(reason)

    differing = {ref: texts for ref, texts in by_ref.items() if len(texts) > 1}
    assert not differing, f"{slug}: {sorted(differing)} read differently in different versions"


def test_the_clinic_explains_the_documents_the_envelope_added():
    """The eleven the clinic gained from the printed envelope. Named individually, because
    "eleven have reasons" would pass if the eleven were the wrong eleven."""
    source = json.loads((ROOT / "packs" / "alderfinch" / "source.json").read_text())
    reasons = build(source, render_images=False).keys["A"]["triage_reasons"]

    assert set(reasons) == {
        "D03", "D11", "N01", "N02", "N03", "N04", "N05", "N06", "N07", "N08", "N09",
    }
    assert "voided before use" in reasons["N01"]
    assert "replenished" in reasons["N06"]
    assert "payroll" in reasons["N02"]
```

- [ ] **Step 2: Run it and watch it fail**

```
$PY -B -m pytest tests/unit/test_triage_reasons.py -q -p no:cacheprovider
```

Expected: every test fails with `KeyError: 'triage_reasons'`. If instead you see a failure about `build` or the source files, stop — the environment is wrong, not the code.

- [ ] **Step 3: Add the field to the schema**

In `originalentry/packs/schema.py`, class `AnswerKey`, directly under `triage`:

```python
class AnswerKey(_Model):
    variant: str
    triage: dict[str, bool] = {}
    #: Why a document needs no entry, by ref — the justification for the triage answer, so it
    #: lives with the answer and never on the document. V17 requires one for every document
    #: this key files and forbids one on a document that takes an entry.
    triage_reasons: dict[str, str] = {}
    designated_journal_documents: dict[str, str] = {}
```

- [ ] **Step 4: Pass it through the generator's whitelist**

`_build_key` in `originalentry/generator/build.py` lists the fields it copies explicitly, so a field absent from that list never reaches the built key. Add it beside `triage`:

```python
    key_dict = {
        "variant": code,
        "triage": answer.get("triage", {}),
        "triage_reasons": answer.get("triage_reasons", {}),
        "designated_journal_documents": answer.get("designated_journal_documents", {}),
```

- [ ] **Step 5: Author Riverbend's three reasons**

In `packs/riverbend/profile.py`, directly above `NO_ENTRY_DOCUMENTS`. The sentences are the ones currently in those documents' `Description` rows, moved verbatim — do not reword them:

```python
# Why each of these needs no entry. It used to be a "Description" row inside the document,
# which handed the student the triage answer they were being marked on. It belongs with the
# answer instead, and reaches the instructor through the answer key (V17).
FILED_REASONS = {
    "N01": "Order for 6 mountain bikes, not to ship before 15 January",
    "N02": "An enquiry about wholesale terms for 25 and 50 units. No order is placed "
           "and no goods are requested.",
    "N03": "Notice of wholesale prices changing from 1 January. No goods have been "
           "ordered or shipped against this notice.",
}
```

- [ ] **Step 6: Author the clinic's eleven reasons**

In `packs/alderfinch/profile.py`, near `GUIDANCE`. These were read out of the printed solution set: its four completed journals contain no entry traceable to any of these, and petty cash appears only as the fund's establishment at 150.00 with no replenishment cheque drawn this period.

```python
# Why each filed document needs no entry, for the instructor copy (V17). The clinic's documents
# come from the printed envelope, which carries no such sentence — so unlike Riverbend's, these
# are authored here and nowhere else. Checked against the printed solution set.
FILED_REASONS = {
    "D03": "An order placed; nothing received and nothing owed yet. The vendor's invoice "
           "records the purchase when the goods arrive.",
    "D11": "An order placed; nothing received and nothing owed yet. The vendor's invoice "
           "records the purchase when the goods arrive.",
    "N01": "Spoiled and voided before use. No money moved; it is kept so the cheque sequence "
           "can be accounted for.",
    "N02": "Supporting record for the payroll cheque. The hours reach the books once, through "
           "the payroll entry, not card by card.",
    "N03": "Supporting record for the payroll cheque. The hours reach the books once, through "
           "the payroll entry, not card by card.",
    "N04": "Supporting record for the payroll cheque. The hours reach the books once, through "
           "the payroll entry, not card by card.",
    "N05": "Supporting record for the payroll cheque. The hours reach the books once, through "
           "the payroll entry, not card by card.",
    "N06": "A disbursement from the petty cash fund. Nothing is journalised until the fund is "
           "replenished, and no replenishment cheque is drawn this period.",
    "N07": "A disbursement from the petty cash fund. Nothing is journalised until the fund is "
           "replenished, and no replenishment cheque is drawn this period.",
    "N08": "A request to book a future appointment. No service has been given and nothing "
           "is owed.",
    "N09": "The clinic's own fee schedule. Not a transaction.",
}
```

- [ ] **Step 7: Write the reasons into both answer arms**

`scripts/build_pack.py` builds answers in two places. Add a helper above them:

```python
def _triage_reasons(profile, triage: dict[str, bool]) -> dict[str, str]:
    """One authored sentence per ref, copied into this version's key for every document this
    version files. Keyed per version because triage is, so a future set can file a document in
    one version only; authored once because three copies would be three places to correct.

    A ref that is filed and has no sentence is not defaulted to "" here. V17 reports it against
    the pack, which names the pack and the version; a silent "" would make the pack valid.
    """
    authored = getattr(profile, "FILED_REASONS", {})
    return {ref: authored[ref] for ref in triage if not triage[ref] and ref in authored}
```

In the manifest arm (around line 959), compute triage once and reuse it:

```python
            triage = {entry["ref"]: entry["entry_for"] is not None for entry in manifest}
            answers[code] = {
                "triage": triage,
                "triage_reasons": _triage_reasons(profile, triage),
                "designated_journal_documents": _designated_journals(
                    manifest, txns_by_no, profile, code),
```

In the Riverbend arm (around line 990):

```python
            triage = ({_ref(t): True for t in txns}
                      | {e["ref"]: False for e in profile.NO_ENTRY_DOCUMENTS})
            answers[code] = {
                "triage": triage,
                "triage_reasons": _triage_reasons(profile, triage),
                "designated_journal_documents": {_ref(t): profile.JOURNAL_OF[t["cycle"]]
                                                  for t in txns},
```

- [ ] **Step 8: Regenerate both packs**

```
$PY -B scripts/build_pack.py riverbend > packs/riverbend/source.json
$PY -B scripts/build_pack.py alderfinch --documents <envelope dir> > packs/alderfinch/source.json
```

Run `$PY -B scripts/build_pack.py --help` first: the clinic needs the printed envelope, regenerated from `../practicesets` per version. `tests/unit/test_document_manifest.py` shows how the envelope is produced. If you cannot produce it, report BLOCKED rather than hand-editing `source.json` — it is generated output and editing it by hand breaks the reproducibility test.

- [ ] **Step 9: Run the test and watch it pass**

```
$PY -B -m pytest tests/unit/test_triage_reasons.py -q -p no:cacheprovider
```

Expected: all five pass.

- [ ] **Step 10: Prove the tests bite**

Delete the `"N06"` entry from the clinic's `FILED_REASONS`, regenerate the clinic, and run the module again. Expected: `test_every_filed_document_has_a_reason_in_every_version` fails naming `N06`, and `test_the_clinic_explains_the_documents_the_envelope_added` fails on the set comparison. Restore the entry and regenerate. Record both results in your report.

- [ ] **Step 11: Check nothing else moved, then commit**

```
$PY -B -m pytest tests/unit/test_riverbend_pack.py tests/unit/test_alderfinch_pack.py -q -p no:cacheprovider
$PY -B -m ruff check originalentry tests scripts
git add originalentry/packs/schema.py originalentry/generator/build.py scripts/build_pack.py \
        packs/riverbend/profile.py packs/alderfinch/profile.py \
        packs/riverbend/source.json packs/alderfinch/source.json \
        tests/unit/test_triage_reasons.py
git commit
```

Commit message subject: `Keep the reason with the answer, not on the document`.

---

### Task 2: V17 makes a missing reason impossible

**Files:**
- Modify: `originalentry/packs/validate.py` (new `_v17_reasons`, called from `validate_pack`'s `if keys is not None:` block)
- Test: `tests/unit/test_triage_reasons.py` (append)

**Interfaces:**
- Consumes: `AnswerKey.triage_reasons` from Task 1.
- Produces: rule `"V17"`, reported as a `Problem(path=f"answer_keys.{code}.triage_reasons", rule="V17", message=...)`. Both packs must pass it.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_triage_reasons.py`:

```python
# ── V17 ──────────────────────────────────────────────────────────────────────────────────

from originalentry.packs import schema                      # noqa: E402
from originalentry.packs.validate import validate_pack      # noqa: E402


def _pack_and_keys(slug: str):
    source = json.loads((ROOT / "packs" / slug / "source.json").read_text())
    generated = build(source, render_images=False)
    return schema.load_pack(generated.pack), {
        code: schema.load_answer_key(key) for code, key in generated.keys.items()
    }


@pytest.mark.parametrize("slug", PACKS)
def test_both_packs_satisfy_v17(slug):
    pack, keys = _pack_and_keys(slug)

    assert [p for p in validate_pack(pack, keys) if p.rule == "V17"] == []


def test_v17_reports_a_filed_document_with_no_reason():
    pack, keys = _pack_and_keys("alderfinch")
    keys["A"].triage_reasons.pop("N06")

    problems = [p for p in validate_pack(pack, keys) if p.rule == "V17"]

    assert len(problems) == 1, problems
    assert "N06" in problems[0].message
    assert problems[0].path == "answer_keys.A.triage_reasons"


def test_v17_reports_a_reason_left_on_a_document_that_takes_an_entry():
    """The half that stops the map rotting: a set changes, a document starts taking an entry,
    and the sentence saying it needs none is still there."""
    pack, keys = _pack_and_keys("alderfinch")
    entered = next(ref for ref, needs in keys["A"].triage.items() if needs)
    keys["A"].triage_reasons[entered] = "Left behind by an earlier version of this set."

    problems = [p for p in validate_pack(pack, keys) if p.rule == "V17"]

    assert len(problems) == 1, problems
    assert entered in problems[0].message


def test_v17_reports_a_reason_that_is_only_whitespace():
    pack, keys = _pack_and_keys("alderfinch")
    keys["A"].triage_reasons["N06"] = "   "

    problems = [p for p in validate_pack(pack, keys) if p.rule == "V17"]

    assert len(problems) == 1, problems
    assert "N06" in problems[0].message
```

- [ ] **Step 2: Run it and watch it fail**

```
$PY -B -m pytest tests/unit/test_triage_reasons.py -q -p no:cacheprovider -k v17
```

Expected: `test_both_packs_satisfy_v17` passes trivially (no V17 exists, so no V17 problems), and the three negative tests fail with `assert 0 == 1`. That asymmetry is the point: the rule does not exist yet.

- [ ] **Step 3: Write the rule**

In `originalentry/packs/validate.py`, after `_v10_coverage`:

```python
def _v17_reasons(pack: Pack, keys: dict[str, AnswerKey], problems: list[Problem]) -> None:
    """A marked judgement has to have a stated reason, and only where it is marked.

    Deciding a document needs no entry is marked, and the instructor copy prints that decision.
    Without the first half it printed eleven blank lines for the clinic. Without the second, a
    reason survives on a document that has since started taking an entry, and a correct note
    becomes a wrong one with nothing to catch it.
    """
    for code, key in keys.items():
        path = f"answer_keys.{code}.triage_reasons"
        for ref, needs_entry in sorted(key.triage.items()):
            reason = key.triage_reasons.get(ref, "")
            if not needs_entry and not reason.strip():
                problems.append(
                    Problem(
                        path,
                        "V17",
                        f"Document {ref!r} needs no entry and records no reason why.",
                    )
                )
            elif needs_entry and ref in key.triage_reasons:
                problems.append(
                    Problem(
                        path,
                        "V17",
                        f"Document {ref!r} takes an entry and carries a no-entry reason.",
                    )
                )
```

Call it in `validate_pack`, inside the `if keys is not None:` block, after `_v10_coverage`:

```python
        _v10_coverage(pack, keys, problems)
        _v17_reasons(pack, keys, problems)
```

- [ ] **Step 4: Run the tests and watch them pass**

```
$PY -B -m pytest tests/unit/test_triage_reasons.py -q -p no:cacheprovider
```

Expected: all nine pass.

- [ ] **Step 5: Prove the rule bites**

Change `if not needs_entry and not reason.strip():` to `if False:` and run the module. Expected: `test_v17_reports_a_filed_document_with_no_reason` and `test_v17_reports_a_reason_that_is_only_whitespace` fail; the other half's test still passes. Restore, then do the same to the `elif` and confirm only the third negative test fails. Record both in your report.

- [ ] **Step 6: Check the rule's documentation and commit**

`validate.py`'s module docstring lists where rules run and keeps `DEFERRED_RULES` for unwritten ones. V17 runs here, so it needs no entry in either — but read the docstring and add V17 to any enumeration of rules that would otherwise be out of date.

```
$PY -B -m pytest tests/unit/test_riverbend_pack.py tests/unit/test_alderfinch_pack.py -q -p no:cacheprovider
$PY -B -m ruff check originalentry tests scripts
git add originalentry/packs/validate.py tests/unit/test_triage_reasons.py
git commit
```

Subject: `V17: a marked judgement has to say why`.

---

### Task 3: The instructor copy reads the key, not the document

**Files:**
- Modify: `scripts/build_walkthrough.py` (`instructor_sections`, the `entry is None` branch and the refusal added in `1a0807c`)
- Modify: `tests/unit/test_alderfinch_pack.py` (`test_a_filed_document_with_no_recorded_reason_stops_the_instructor_copy`)
- Test: `tests/unit/test_alderfinch_pack.py`, `tests/unit/test_riverbend_pack.py`

**Interfaces:**
- Consumes: `AnswerKey.triage_reasons` (Task 1), guaranteed non-empty by V17 (Task 2). `instructor_sections(src: dict, version: str, key: dict) -> str` keeps its signature; `key` is the dict from `build(src).keys[version]`.
- Produces: nothing later tasks consume.

**Read this before you start.** Task 1 gave the clinic its reasons, so the refusal that `1a0807c` added no longer fires for it — and `tests/unit/test_alderfinch_pack.py::test_a_filed_document_with_no_recorded_reason_stops_the_instructor_copy` asserts that it *does*. That test is now wrong about the world and must change in this task. It is not a regression you caused. Replace it with two tests: the clinic's copy builds and prints its reasons, and the refusal still fires for a key that is missing one.

- [ ] **Step 1: Write the failing tests**

In `tests/unit/test_alderfinch_pack.py`, replace `test_a_filed_document_with_no_recorded_reason_stops_the_instructor_copy` with:

```python
def test_the_instructor_copy_says_why_each_filed_document_needs_no_entry(generated):
    """It printed "no entry required" above a blank line eleven times, because it read the
    reason from a "Description" field that a pack built from the printed envelope does not
    have. The reason now comes from the answer key."""
    src = json.loads(SOURCE.read_text())

    html = _walkthrough(src, "A", generated.keys["A"])

    assert "voided before use" in html
    assert "no replenishment cheque is drawn this period" in html
    assert "not card by card" in html
    assert "no entry required" in html


def test_the_instructor_copy_still_refuses_when_a_reason_is_missing(generated):
    """V17 should stop a pack like this reaching here at all. The refusal stays because the
    walkthrough is run by hand against whatever source.json is on disk, which is exactly when
    a blank would go unnoticed."""
    src = json.loads(SOURCE.read_text())
    key = json.loads(json.dumps(generated.keys["A"]))
    key["triage_reasons"].pop("N06")

    with pytest.raises(SystemExit) as refusal:
        _walkthrough(src, "A", key)

    message = str(refusal.value)
    assert "N06" in message
    assert "Nothing was written." in message
```

- [ ] **Step 2: Run them and watch them fail**

```
$PY -B -m pytest tests/unit/test_alderfinch_pack.py -q -p no:cacheprovider -k instructor
```

Expected: the first fails because the reason is not in the html (the walkthrough still reads `Description`, which the clinic has none of, so it refuses and the test errors on `SystemExit`); the second passes already, for the wrong reason — it refuses for *every* ref, not just `N06`. Both become honest in Step 3.

- [ ] **Step 3: Read the reason from the key**

In `scripts/build_walkthrough.py`, inside `instructor_sections`, the `if entry is None:` branch currently reads:

```python
            why = dict(d["variants"][version]["text_alternative"]["fields"]).get("Description", "")
```

Replace it with:

```python
            # From the answer key, where the reason lives (V17). It used to be read out of a
            # "Description" row in the document's own text, which both handed the student the
            # answer and left a pack built from a printed envelope with nothing to print.
            why = (answer.get("triage_reasons") or {}).get(ref, "")
```

Leave the refusal below it exactly as it is: it collects `unexplained` and raises with the refs named. Its message says "Record a reason for each, where a student will not read it", which is still the right instruction.

- [ ] **Step 4: Run the tests and watch them pass**

```
$PY -B -m pytest tests/unit/test_alderfinch_pack.py tests/unit/test_riverbend_pack.py -q -p no:cacheprovider
```

Expected: both new tests pass, and Riverbend's existing `test_the_no_entry_documents_say_so_and_say_why` still passes — its `"not to ship before 15 January"` now arrives from `FILED_REASONS` rather than from the document. If that test fails, the move in Task 1 Step 5 changed the sentence; restore it verbatim.

- [ ] **Step 5: Prove it bites**

Change `why` back to reading the `Description` field and run the module. Expected: the clinic's "says why" test fails. Restore. Then, separately, delete the `if not why.strip():` guard and confirm the refusal test fails. Record both.

- [ ] **Step 6: Commit**

```
$PY -B -m ruff check originalentry tests scripts
git add scripts/build_walkthrough.py tests/unit/test_alderfinch_pack.py
git commit
```

Subject: `Read the reason from the key the instructor marks against`.

---

### Task 4: The transaction's description stops reaching the student

**Files:**
- Modify: `scripts/build_pack.py` (delete the `Description` append, around line 424)
- Modify: `packs/riverbend/profile.py` (delete the `Description` row from each of the three `NO_ENTRY_DOCUMENTS` entries, at lines 102, 109-111 and 118-120)
- Modify: `tests/unit/test_riverbend_pack.py:136-143` (`test_every_document_says_what_it_is_for_and_how_much`)
- Create: `tests/unit/test_no_transaction_list.py`
- Regenerate: `packs/riverbend/source.json`, `packs/alderfinch/source.json`

**Interfaces:**
- Consumes: `FILED_REASONS` and `triage_reasons` from Task 1, which is why the three sentences can be deleted from the documents without being lost.
- Produces: nothing later tasks consume.

- [ ] **Step 1: Capture the baseline that must not move**

Riverbend is live. Before changing anything, record what has to come out identical:

```
git show HEAD:packs/riverbend/source.json > /tmp/riverbend-before.json
```

- [ ] **Step 2: Write the failing test**

Create `tests/unit/test_no_transaction_list.py`:

```python
"""The product's claim, kept: there is no transaction list.

README.md and CASES.md both say it in bold. The online pack said otherwise, one line per
document: every Riverbend document carried a "Description" row holding the model's own
description of the transaction, and for five of them that row stated the designed error the
student was supposed to find for themselves.

One assertion over both packs, because the row had two sources — the builder wrote 84 of the 93
document/variant pairs from txn["desc"] and the profile authored the other 9 — and a change that
fixed one source looked complete.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PACKS = ("riverbend", "alderfinch")

# Each designed error, and the phrase the Description row used to hand the student. Written out
# rather than derived: deriving them from the same source that produced them could not fail.
#
# Each phrase must hold for all three versions. D22's figures rotate per version — 40 billed
# against 38 received in A, 44/42 in B, 48/46 in C — so the phrase is the part that gives the
# trap away whatever the quantities are. "receiving report shows 38 received" would have been
# an assertion that could not fail for two versions out of three.
GAVE_THE_ANSWER_AWAY = {
    "D04": "in full",
    "D07": "FOB shipping point",
    "D18": "within 1/15 discount",
    "D22": "receiving report shows",
    "D23": "outside the discount period",
}


def _documents(slug: str):
    return json.loads((ROOT / "packs" / slug / "source.json").read_text())["documents"]


@pytest.mark.parametrize("slug", PACKS)
def test_no_document_carries_a_description_row(slug):
    offenders = []
    for document in _documents(slug):
        for code, variant in document["variants"].items():
            fields = (variant.get("text_alternative") or {}).get("fields") or []
            if any(label == "Description" for label, _ in fields):
                offenders.append(f"{document['ref']}/{code}")

    assert not offenders, f"{slug}: {len(offenders)} still describe the transaction: {offenders[:6]}"


def test_no_riverbend_document_states_its_own_designed_error():
    """The five traps, by the phrase each used to give away. A student has to find these by
    reading the documents, which is the skill the set exists to teach."""
    by_ref = {d["ref"]: d for d in _documents("riverbend")}

    for ref, phrase in GAVE_THE_ANSWER_AWAY.items():
        document = by_ref[ref]
        for code, variant in document["variants"].items():
            text = json.dumps(variant.get("text_alternative") or {})
            assert phrase not in text, f"{ref}/{code} still says {phrase!r}"


@pytest.mark.parametrize("slug", PACKS)
def test_every_document_still_identifies_itself(slug):
    """Removing a row must not leave a document a student cannot read. Riverbend has no images,
    so this text is the whole document."""
    for document in _documents(slug):
        for code, variant in document["variants"].items():
            text_alt = variant.get("text_alternative") or {}
            fields = text_alt.get("fields") or []
            informative = {label for label, _ in fields} - {"Date", "Document"}
            assert informative or text_alt.get("lines"), (
                f"{slug} {document['ref']}/{code} says nothing but its own name and date"
            )
```

- [ ] **Step 3: Run it and watch it fail**

```
$PY -B -m pytest tests/unit/test_no_transaction_list.py -q -p no:cacheprovider
```

Expected: `test_no_document_carries_a_description_row[riverbend]` fails naming 93 pairs, and the alderfinch parametrisation and the self-identification test pass.

**Check the designed-error test more carefully than that.** It must be failing because all five phrases are present in all three versions — fifteen ways, not one. Run it with `-x` off and confirm the first failure names D04, then comment out D04's entry and re-run to see D07 fail, and so on through all five. A phrase that is absent from a version today makes that assertion unable to fail there forever, which is how the first draft of this plan shipped a D22 phrase that only existed in version A. If any phrase is absent for any version, find the version-invariant part of the sentence and use that instead, and say so in your report.

- [ ] **Step 4: Stop the builder writing it**

In `scripts/build_pack.py`, delete both the comment and the line:

```python
    # What the document is about, in the words on the paper.
    fields.append(["Description", txn["desc"]])
```

The comment was the false belief that kept this in place — the words are the transaction's, and they appear on no document — so it goes with the line rather than being corrected.

- [ ] **Step 5: Stop the profile authoring it**

In `packs/riverbend/profile.py`, delete the `["Description", ...]` element from each of the three `NO_ENTRY_DOCUMENTS` entries (N01 at line 102, N02 at 109-111, N03 at 118-120). The sentences already live in `FILED_REASONS` from Task 1; do not delete them from there.

- [ ] **Step 6: Invert the test that required the row**

In `tests/unit/test_riverbend_pack.py`, `test_every_document_says_what_it_is_for_and_how_much` asserts both an `Amount` and a `Description`. Keep the first, invert the second, and rename the test so its name matches what it now checks:

```python
@pytest.mark.parametrize("version", ["A", "B", "C"])
def test_every_document_says_how_much_without_saying_what_happened(generated, version):
    """The Amount half is unchanged. The Description half asserted the defect: it required
    every document to carry the transaction's own description, which is the transaction list
    the set is built not to give.
    """
    pack = schema.load_pack(generated.pack)

    for document in pack.documents:
        text = document.variants[version].text_alternative
        labels = {label for label, _ in text.fields}
        assert "Amount" in labels, f"{document.display_ref} carries no amount"
        assert "Description" not in labels, (
            f"{document.display_ref} describes the transaction to the student"
        )
```

- [ ] **Step 7: Regenerate both packs**

```
$PY -B scripts/build_pack.py riverbend > packs/riverbend/source.json
$PY -B scripts/build_pack.py alderfinch --documents <envelope dir> > packs/alderfinch/source.json
```

- [ ] **Step 8: Prove nothing but the text moved**

Riverbend's marking must be untouched. Run this and expect it to print nothing but `identical`:

```python
$PY -B - <<'PY'
import json
before = json.load(open("/tmp/riverbend-before.json"))
after = json.load(open("packs/riverbend/source.json"))

assert [d["ref"] for d in before["documents"]] == [d["ref"] for d in after["documents"]], "documents moved"
for field in ("accounts", "parties", "journals", "checkpoints", "rubric", "variants", "transactions"):
    assert before.get(field) == after.get(field), f"{field} changed"
for code, a in before["answers"].items():
    b = after["answers"][code]
    for field in ("triage", "designated_journal_documents", "expected_entries",
                  "adjustments", "error_signatures"):
        assert a.get(field) == b.get(field), f"answers.{code}.{field} changed"
print("identical")
PY
```

If any assertion fires, stop and report it. A change here means the removal touched marking, which this work must not do.

Then confirm the built key's figures are unchanged too:

```
$PY -B -m pytest tests/unit/test_riverbend_pack.py -q -p no:cacheprovider
```

- [ ] **Step 9: Run the new tests and watch them pass**

```
$PY -B -m pytest tests/unit/test_no_transaction_list.py tests/unit/test_triage_reasons.py -q -p no:cacheprovider
```

Expected: all pass.

- [ ] **Step 10: Prove the tests bite**

Restore `fields.append(["Description", txn["desc"]])`, regenerate Riverbend, and run `tests/unit/test_no_transaction_list.py`. Expected: the no-Description test fails naming 84 pairs and the designed-error test fails. Remove it again and regenerate. Separately, restore N02's authored `Description` row, regenerate, and confirm the no-Description test fails with 3 pairs — this is the mutation that proves deleting only the builder's line is not enough. Record both.

- [ ] **Step 11: Commit**

```
$PY -B -m ruff check originalentry tests scripts
git add scripts/build_pack.py packs/riverbend/profile.py packs/riverbend/source.json \
        packs/alderfinch/source.json tests/unit/test_riverbend_pack.py \
        tests/unit/test_no_transaction_list.py
git commit
```

Subject: `Stop describing the transaction on the document`.

---

### Task 5: The gate

**Files:** none. This task changes nothing and produces a report.

**Interfaces:** consumes the finished tree.

- [ ] **Step 1: Validate both packs**

```
$PY -B scripts/generate_pack.py packs/riverbend/source.json /tmp/riverbend.zip
$PY -B scripts/generate_pack.py packs/alderfinch/source.json /tmp/alderfinch.zip
FLASK_APP=originalentry.app:create_app $PY -B -m flask packs validate /tmp/riverbend.zip
FLASK_APP=originalentry.app:create_app $PY -B -m flask packs validate /tmp/alderfinch.zip
```

Both must print `Valid.` Record the variant and image counts each reports.

- [ ] **Step 2: Build the clinic's instructor copy**

It has refused since `1a0807c`. It must build now.

```
$PY -B scripts/build_walkthrough.py packs/alderfinch/source.json --instructor A
```

Open the PDF and confirm the eleven filed documents each print a reason rather than a blank line.

- [ ] **Step 3: Read Riverbend's documents as a student would**

The spec requires this and it cannot be automated. For each of the 31 documents, read the text a student now sees and judge whether it still reads as the artefact it represents. Report any that do not — by ref, with what is missing. The spec names N02, the request for quotation, as the one most likely to be too thin: it is left with `Date`, `Document`, `From`, `Reference` and `Amount: None stated`, and no line items.

```python
$PY -B - <<'PY'
import json
src = json.load(open("packs/riverbend/source.json"))
for d in src["documents"]:
    v = d["variants"]["A"]["text_alternative"]
    print(f"\n{d['ref']}  {d['display_ref']}")
    for label, value in v["fields"]:
        print(f"    {label:20} | {value}")
    for line in v.get("lines", []):
        print(f"    line: {line}")
PY
```

- [ ] **Step 4: Run the full suite, once**

```
$PY -B -m pytest tests/ -q -p no:cacheprovider
```

It takes about an hour. Nothing else may run against the database while it does. Report the count and any failure in full.

- [ ] **Step 5: Report, and stop**

`flask packs import` is not yours to run: it writes to a shared live Postgres with students working Riverbend in it. Report the validate results, the suite result, and your reading of the 31 documents. The decision to import belongs to the person who knows where those students are.

---

## Self-Review

**Spec coverage.** Every section of the spec maps to a task: the two removal sources to Task 4 Steps 4 and 5 with a mutation proving each separately; `triage_reasons` and `FILED_REASONS` to Task 1; V17's two halves to Task 2; the walkthrough to Task 3; regeneration and the Riverbend invariant to Task 4 Step 8; the import boundary and the manual read of the 31 to Task 5. The spec's "what this does not fix" needs no task — D22's structural leak and `_face_amount` are explicitly deferred, and Task 4's `GAVE_THE_ANSWER_AWAY` only asserts the *phrase* is gone from D22, not that its quantities are, which is consistent with the spec saying step one leaves that trap open.

**Placeholders.** One deliberate gap: the clinic's regeneration needs an envelope directory, written as `<envelope dir>` in Task 1 Step 8 and Task 4 Step 7, because the path depends on where the implementer regenerates `../practicesets` output. The step says to read `--help` and `tests/unit/test_document_manifest.py` for how, and to report BLOCKED rather than hand-edit generated JSON.

**Type consistency.** `triage_reasons` is `dict[str, str]` in the schema, the generator whitelist, the builder helper, V17 and the walkthrough. `FILED_REASONS` is `dict[str, str]` keyed by ref in both profiles, read only through `getattr(profile, "FILED_REASONS", {})` so a profile without one is not an error. `_triage_reasons(profile, triage)` takes the triage map and returns the reasons map; both call sites compute `triage` into a local first, which is a change to the existing lines and is shown in full.

One risk the plan carries on purpose: Task 1 leaves Riverbend's three sentences in two places until Task 4 deletes one. A reviewer seeing Task 1 alone will find duplication. Task 1's Interfaces block says so and says why.

**One defect this review found and fixed.** The first draft's `GAVE_THE_ANSWER_AWAY` gave D22 the phrase `"receiving report shows 38 received"`. Checked against the real pack: D22's quantities rotate per version — 40/38 in A, 44/42 in B, 48/46 in C — so that assertion could not have failed for two versions out of three. It is now the version-invariant `"receiving report shows"`, and Task 4 Step 3 was rewritten to require the test to be seen failing fifteen ways rather than one, because the original "expected: fails on D04's phrase" would have accepted the broken version. This is the plan's own named defect class — a check that cannot fail — found in the plan written to remove an instance of it.
