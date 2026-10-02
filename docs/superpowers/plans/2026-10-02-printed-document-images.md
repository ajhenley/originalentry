# Printed Document Images Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show a student on screen the same document a student on paper holds, by taking the online document inventory from the printed set and shipping each printed artefact as the document's image.

**Architecture:** `gendocs.py` gains a manifest — one HTML file per printed artefact plus a JSON index naming each one's kind, reference, date and transaction. The pack translator takes its document list from that manifest instead of from the transaction list, and a renderer turns each artefact's HTML into a trimmed PNG through the same CSS the paper set uses. The student page puts the image first and keeps the text behind a disclosure.

**Tech Stack:** Python 3.13+, WeasyPrint (HTML→PDF, already used by `tools/topdf.py`), pypdfium2 (PDF→raster), Pillow (trim), Jinja2.

**Spec:** `docs/superpowers/specs/2026-10-02-document-inventory-design.md`

## Global Constraints

- Python >= 3.13. Run with `.venv/bin/python -B`, pytest with `-p no:cacheprovider`. Stale bytecode has already made a failing test look like a passing one in this project.
- **Riverbend's printed output must not change by one byte.** `generators/gendocs.py` currently produces it correctly; every change here is additive. Prove it each task by diffing all three versions against the pre-change output.
- **`packs/riverbend/source.json` is not edited**, and its sha256 stays `5a33745ae09902e01eafd61f8e11b37fe31ace0970a7deadc7b636a65f55e308`.
- The translator reads figures and invents none.
- `ruff check originalentry tests scripts` must pass; it is a CI step.
- Alder & Finch only. Riverbend is live with four versions and students in it; Thorne & Meadow is not online.
- No pack text may contain correct, incorrect, right or wrong, nor a money figure to one decimal place.
- Images: PNG, under 2 MB each, at most 2000 archive entries and 200 MB uncompressed.

## Context the implementer needs

**Two reasons a student sees no image today, and both matter.** The packs carry none — Riverbend and the clinic were both generated with `--paper`. And the image route refuses outright for paper-mode assignments:

```python
if assignment is None or assignment.mode != "screen":
    abort(404)
```

So this work only ever shows up on **screen-mode** assignments. A paper student has the envelope and the app does not duplicate it.

**The inventories differ**, which is why the images cannot simply be bolted on: the clinic's envelope holds 26 artefacts and its pack 17. Of those 17, seven cannot be matched to a printed artefact by scraping — some carry no number, one pack document covers two artefacts, and two were authored into the profile with no printed counterpart at all.

**`gendocs.py` is heterogeneous.** 14 sections, 15 emit sites, plus 7 more in three company modules. Six sections build a `halves`/`thirds`/`tapes` list and only then group two or three onto a page, so the per-artefact boundary exists at the list append, not at the `PAGES.append`. `page(cls, stock, body)` takes no identifier, so it cannot be instrumented centrally without losing which artefact it just emitted. Section 14 hands `page` to company code.

## File Structure

| File | Responsibility |
| --- | --- |
| `practicesets/generators/gendocs.py` | Gains `emit()` and writes `manifest.json` + one HTML file per artefact. Combined sheet unchanged. |
| `practicesets/companies/*.py` | `no_entry_documents(ctx)` gains `emit` in its ctx and uses it. |
| `originalentry/scripts/render_documents.py` | New. Manifest HTML → trimmed PNG. |
| `originalentry/scripts/build_pack.py` | Takes the document list from the manifest. |
| `originalentry/packs/alderfinch/profile.py` | Loses `NO_ENTRY_DOCUMENTS`; gains the manifest path. |
| `originalentry/templates/student/document.html` | Image first; text in a `<details>`. |
| `originalentry/tests/unit/test_document_manifest.py` | The manifest's shape and completeness. |
| `originalentry/tests/unit/test_document_render.py` | A rendered artefact is a real PNG of sane size. |

---

### Task 1: gendocs records what it emits

**Files:**
- Modify: `practicesets/generators/gendocs.py`
- Modify: `practicesets/companies/alderfinch.py`, `riverbend.py`, `thornemeadow.py`

**Interfaces:**
- Produces: `emit(kind, ref, txn, html) -> str` in `gendocs.py`, returning `html` unchanged so it can wrap an existing expression. Writes `manifest.json` and `documents/<ref>.html` into `PRACTICESET_OUT`.

The manifest entry shape, which Task 3 consumes:

```json
{"ref": "D03", "kind": "vendor_invoice", "printed_ref": "CV-3310",
 "date": "Dec 2", "txn": 3, "file": "documents/D03.html"}
```

`ref` is `D{txn:02d}` where a transaction drives the artefact, and `N{nn}` numbered in printed order where none does. `txn` is `null` for those.

- [ ] **Step 1: Write the failing test**

Create `practicesets/tests/test_manifest.py`:

```python
"""The manifest is how the online set learns what is in the envelope.

Without it the two inventories drift: the clinic's envelope holds 26 artefacts and its pack 17,
and seven of those 17 cannot be matched to a printed document at all.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _build(company):
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, PRACTICESET_COMPANY=company, PRACTICESET_OUT=tmp)
        subprocess.run([sys.executable, "generators/gendocs.py", "B"],
                       cwd=ROOT, env=env, check=True, capture_output=True)
        manifest = json.loads((Path(tmp) / "manifest.json").read_text())
        files = {p.name for p in (Path(tmp) / "documents").glob("*.html")}
        sheet = (Path(tmp) / "docs_B.html").read_text()
        return manifest, files, sheet


def test_every_printed_artefact_is_in_the_manifest():
    """26 for the clinic. If the manifest is short, some document is invisible to the online set
    exactly as it is invisible to tools/audit.py today."""
    manifest, _, sheet = _build("alderfinch")
    printed = sheet.count('<div class="pg ') + sheet.count('<div class="half') + \
        sheet.count('<div class="third')

    assert len(manifest) == printed, f"{len(manifest)} manifest entries for {printed} artefacts"


def test_every_manifest_entry_has_its_own_file():
    manifest, files, _ = _build("alderfinch")

    assert {Path(e["file"]).name for e in manifest} == files
    for entry in manifest:
        assert entry["ref"], entry
        assert entry["kind"], entry


def test_refs_are_unique():
    manifest, _, _ = _build("alderfinch")
    refs = [e["ref"] for e in manifest]

    assert len(refs) == len(set(refs)), sorted(r for r in refs if refs.count(r) > 1)


def test_a_transaction_backed_artefact_names_its_transaction():
    """Which documents start a clock is the whole of triage, and it is read from here."""
    manifest, _, _ = _build("alderfinch")
    by_ref = {e["ref"]: e for e in manifest}

    assert by_ref["D03"]["txn"] == 3
    assert any(e["txn"] is None for e in manifest), "nothing is filed-not-entered"
```

- [ ] **Step 2: Run it to watch it fail**

Run: `cd /Volumes/Nevvie/Library/Dropbox/habichuela123/practicesets && .venv/bin/python -B -m pytest tests/test_manifest.py -v -p no:cacheprovider`
Expected: FAIL — there is no `manifest.json`, so `_build` raises `FileNotFoundError`.

(The repository has no `tests/` directory or pytest configuration yet. Create `tests/__init__.py` and confirm `.venv/bin/python -B -m pytest --version` works before Step 1; if pytest is absent, `.venv/bin/pip install pytest` and say so in your report.)

- [ ] **Step 3: Add the recorder**

In `gendocs.py`, after `PAGES=[]` (line 36):

```python
# What was printed, so the online set can contain the same documents rather than a different
# list that drifted. The combined sheet below is untouched; this is an additional output.
MANIFEST: list[dict] = []
_DOCS_DIR = _os.path.join(OUT, "documents")
_os.makedirs(_DOCS_DIR, exist_ok=True)
_no_entry_seq = 0


def emit(kind, html, *, txn=None, printed_ref=None, date=None):
    """Record one printed artefact and return its html unchanged.

    Returning the html means a call site wraps what it already built rather than being
    restructured, which is what keeps the printed sheet byte-identical.
    """
    global _no_entry_seq
    if txn is None:
        _no_entry_seq += 1
        ref = f"N{_no_entry_seq:02d}"
    else:
        ref = f"D{txn:02d}"
        if any(e["ref"] == ref for e in MANIFEST):           # three documents share a purchase
            ref = f"{ref}-{sum(1 for e in MANIFEST if e['ref'].startswith(ref)) + 1}"
    MANIFEST.append({"ref": ref, "kind": kind, "printed_ref": printed_ref,
                     "date": date or (T[txn]["date"] if txn in T else None),
                     "txn": txn, "file": f"documents/{ref}.html"})
    open(_os.path.join(_DOCS_DIR, f"{ref}.html"), "w").write(html)
    return html
```

- [ ] **Step 4: Wrap every emit site**

There are 15 in `gendocs.py`. For a section that calls `page()`, wrap the body:

```python
page(HOUSE, "stock-white", emit("customer_po", body, txn=no, printed_ref=ponum))
```

For a section that appends to `halves`/`thirds`/`tapes`, wrap at the append — that is where the per-artefact boundary exists:

```python
halves.append(emit("bill_of_lading", f'''<div class="half ...">...</div>''', txn=no, printed_ref=b))
```

Work section by section, running the printed-sheet diff (Step 6) after each. The sections and their identifiers:

| Section | kind | txn | printed_ref |
| --- | --- | --- | --- |
| 1 customer POs | `customer_po` | `no` | `ponum` |
| 2 own invoices | `sales_invoice` | `no` | `t['meta']['inv']` |
| 3 bills of lading | `bill_of_lading` | `no` | `b` |
| 4 credit memo | `credit_memo` | `CM["txn"]` | `CM["ref"]` |
| 5 remittances | `remittance` | `no` | `cno` |
| 5b receipts | `receipt` | `no` | `number` |
| 6 register tapes | `register_tape` | `no` | `None` |
| 7 outgoing POs | `purchase_order` | `no` | `m["po"]` |
| 8 vendor invoices | `vendor_invoice` | `no` | `m["vinv"]` |
| 9 receiving reports | `receiving_report` | `no` | `m["rr"]` |
| 10 cheques | `cheque` | `no` | `cno` |
| 10 void cheque | `void_cheque` | `None` | `VOID_NO` |
| 11 time cards | `time_card` | `None` | `nm` |
| 12 payroll register | `payroll_register` | `None` | `None` |
| 13 vouchers | `petty_cash_voucher` | `None` | `n` |

- [ ] **Step 5: Let the company's own documents in**

Section 14 passes a ctx to the company. Add `emit` to it:

```python
no_entry_documents(dict(RB=RB, DESC=DESC, CINFO=CINFO, VINFO=VINFO, head=head, page=page, emit=emit))
```

Then in each of the three companies' `no_entry_documents`, wrap each body — for example in `alderfinch.py`:

```python
    page(cls, "stock-white", ctx["emit"]("appointment_request", body, printed_ref="AR-3120"))
```

Riverbend has three such documents, Alder & Finch two, Thorne & Meadow two.

- [ ] **Step 6: Prove the printed sheet did not move**

```bash
cd /Volumes/Nevvie/Library/Dropbox/habichuela123/practicesets
git stash list   # must be empty; do not use git stash in this repo
mkdir -p /tmp/sheet-before /tmp/sheet-after
git show HEAD:generators/gendocs.py > /tmp/gendocs-head.py
cp generators/gendocs.py /tmp/gendocs-mine.py
cp /tmp/gendocs-head.py generators/gendocs.py
for c in riverbend alderfinch thornemeadow; do for v in A B C; do
  PRACTICESET_COMPANY=$c PRACTICESET_OUT=/tmp/sheet-before .venv/bin/python -B generators/gendocs.py $v >/dev/null
  mv /tmp/sheet-before/docs_$v.html /tmp/sheet-before/$c-$v.html; done; done
cp /tmp/gendocs-mine.py generators/gendocs.py
for c in riverbend alderfinch thornemeadow; do for v in A B C; do
  PRACTICESET_COMPANY=$c PRACTICESET_OUT=/tmp/sheet-after .venv/bin/python -B generators/gendocs.py $v >/dev/null
  mv /tmp/sheet-after/docs_$v.html /tmp/sheet-after/$c-$v.html; done; done
for f in /tmp/sheet-before/*.html; do
  diff -q "$f" "/tmp/sheet-after/$(basename $f)" || echo "CHANGED: $(basename $f)"; done
echo "if nothing printed CHANGED, all nine sheets are identical"
```

All nine must be identical. If one differs, the wrap altered the html; find it rather than accepting it.

- [ ] **Step 7: Run the tests and commit**

Run: `.venv/bin/python -B -m pytest tests/test_manifest.py -v -p no:cacheprovider`
Expected: 4 passed.

```bash
git add generators/gendocs.py companies/*.py tests/
git commit -m "Record what the envelope contains

The printed set and the online set hold different documents: the clinic's envelope has 26
artefacts and its pack 17, and seven of those cannot be matched to a printed document at all.
Nothing could see it, because each side is internally consistent.

gendocs now writes a manifest beside the sheet it already prints — one file per artefact, with
the kind, the printed reference and the transaction that drives it, or none where a document is
filed rather than entered. The sheet itself is unchanged in all nine company-version pairs."
```

---

### Task 2: render an artefact to a picture

**Files:**
- Create: `originalentry/scripts/render_documents.py`
- Create: `originalentry/tests/unit/test_document_render.py`

**Interfaces:**
- Consumes: the manifest and per-artefact HTML from Task 1.
- Produces: `render_png(fragment: str, css: str) -> bytes` and `render_manifest(set_dir: Path) -> dict[str, bytes]` keyed by manifest ref. `render_png` takes the html *string*, not a path, so Task 3 can render a fragment it already holds.

WeasyPrint 70 has no `write_png`, so the path is HTML → PDF → raster → trim. `pypdfium2` is a pure wheel and keeps this reproducible across machines; `tools/topdf.py` already depends on WeasyPrint and pypdf, so this is one more laptop-only dependency in the same family as Pillow.

- [ ] **Step 1: Write the failing test**

```python
"""A document picture is the document, not a diagram of it."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SETS = ROOT.parent / "practicesets"
ALLOW_NO_SETS = os.environ.get("PACK_TRANSLATOR_ALLOW_NO_SETS") == "1"


def _require_sets():
    if SETS.is_dir():
        return
    if ALLOW_NO_SETS:
        pytest.skip("PACK_TRANSLATOR_ALLOW_NO_SETS=1")
    pytest.fail(f"The practice sets are not at {SETS}, so the only test that renders a real "
                f"document cannot run. Check practicesets out beside this repository, or set "
                f"PACK_TRANSLATOR_ALLOW_NO_SETS=1 to accept the gap knowingly.")


def _clinic_documents(tmp):
    env = dict(os.environ, PRACTICESET_COMPANY="alderfinch", PRACTICESET_OUT=str(tmp))
    subprocess.run([sys.executable, "generators/gendocs.py", "B"],
                   cwd=SETS, env=env, check=True, capture_output=True)
    return Path(tmp)


def test_a_rendered_document_is_a_png_a_student_can_read():
    _require_sets()
    from scripts.render_documents import render_manifest

    with tempfile.TemporaryDirectory() as tmp:
        images = render_manifest(_clinic_documents(tmp))

    assert images, "nothing rendered"
    for ref, data in images.items():
        assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{ref} is not a PNG"
        assert 2_000 < len(data) < 2 * 1024 * 1024, f"{ref} is {len(data)} bytes"


def test_the_picture_is_trimmed_rather_than_a_sheet_of_paper():
    """A half-sheet rendered on an auto page is two thirds white. A student zooming a document
    should get the document."""
    _require_sets()
    from PIL import Image
    import io
    from scripts.render_documents import render_manifest

    with tempfile.TemporaryDirectory() as tmp:
        images = render_manifest(_clinic_documents(tmp))

    for ref, data in images.items():
        im = Image.open(io.BytesIO(data))
        assert im.height < 1400, f"{ref} is {im.width}x{im.height}: untrimmed"
```

- [ ] **Step 2: Run it to watch it fail**

Run: `.venv/bin/python -B -m pytest tests/unit/test_document_render.py -v -p no:cacheprovider`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.render_documents'`.

- [ ] **Step 3: Install the rasteriser and write the renderer**

```bash
.venv/bin/pip install pypdfium2
```

Create `scripts/render_documents.py`:

```python
"""Turn each printed artefact into the picture a student sees.

The document a student reads on screen should be the document a student on paper holds, so this
renders the paper set's own html through the paper set's own stylesheet. It does not draw a
document; it photographs one.

WeasyPrint dropped PNG output, so the path is html to pdf to raster. The page is auto-sized and
then trimmed, because a half-sheet artefact rendered onto a full page is mostly white paper.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pypdfium2
from PIL import Image, ImageChops
from weasyprint import HTML

SCALE = 2.2          # renders a 750px-wide invoice at about 1650px, legible when zoomed
PAD = 18             # white margin left around the trimmed document


def render_png(fragment: str, css: str) -> bytes:
    document = (f"<!DOCTYPE html><html><head><meta charset='utf-8'><style>{css}\n"
                f"@page {{ size: auto; margin: 0 }} body {{ margin: 0 }}"
                f"</style></head><body>{fragment}</body></html>")
    pdf = io.BytesIO()
    HTML(string=document).write_pdf(pdf)
    pdf.seek(0)
    page = pypdfium2.PdfDocument(pdf)[0]
    image = page.render(scale=SCALE).to_pil().convert("RGB")

    blank = Image.new("RGB", image.size, (255, 255, 255))
    box = ImageChops.difference(image, blank).getbbox()
    if box:
        image = image.crop(box)
    canvas = Image.new("RGB", (image.width + PAD * 2, image.height + PAD * 2), (255, 255, 255))
    canvas.paste(image, (PAD, PAD))

    out = io.BytesIO()
    canvas.save(out, format="PNG", optimize=True)
    return out.getvalue()


def render_manifest(set_dir: Path) -> dict[str, bytes]:
    """Every artefact the manifest names, keyed by its ref."""
    manifest = json.loads((set_dir / "manifest.json").read_text())
    css = _stylesheet(set_dir)
    return {entry["ref"]: render_png((set_dir / entry["file"]).read_text(), css)
            for entry in manifest}


def _stylesheet(set_dir: Path) -> str:
    """The paper set's own stylesheet, taken from the sheet it printed."""
    import re

    sheet = next(set_dir.glob("docs_*.html")).read_text()
    found = re.search(r"<style>(.*?)</style>", sheet, re.S)
    if not found:
        raise SystemExit(f"no stylesheet in {set_dir}; the documents would render unstyled.")
    return found.group(1)
```

- [ ] **Step 4: Run the tests to watch them pass**

Run: `.venv/bin/python -B -m pytest tests/unit/test_document_render.py -v -p no:cacheprovider`
Expected: 2 passed.

- [ ] **Step 5: Look at one**

```bash
.venv/bin/python -B -c "
import tempfile, subprocess, sys, os, pathlib
from scripts.render_documents import render_manifest
tmp = tempfile.mkdtemp()
subprocess.run([sys.executable,'generators/gendocs.py','B'], cwd='../practicesets',
               env=dict(os.environ, PRACTICESET_COMPANY='alderfinch', PRACTICESET_OUT=tmp), check=True)
imgs = render_manifest(pathlib.Path(tmp))
pathlib.Path('/tmp/look.png').write_bytes(imgs['D02'])
print('wrote /tmp/look.png', len(imgs['D02']), 'bytes')
"
open /tmp/look.png
```

It must look like the clinic's sales invoice — teal letterhead, SOLD TO, terms, item table, total. If it is unstyled or clipped, stop and report rather than adjusting the scale to hide it.

- [ ] **Step 6: Commit**

```bash
git add scripts/render_documents.py tests/unit/test_document_render.py pyproject.toml
git commit -m "Photograph the document rather than drawing one

The existing renderer draws a header bar, the fields and the line items in Pillow's built-in
font; it calls itself deliberately plain, and it is. This renders the paper set's own html
through the paper set's own stylesheet, so the picture on screen is the document in the envelope.

Auto-sized then trimmed: a half-sheet artefact on a full page is mostly white paper."
```

---

### Task 3: the pack takes its documents from the envelope

**Files:**
- Modify: `originalentry/scripts/build_pack.py`
- Modify: `originalentry/packs/alderfinch/profile.py`
- Create: `originalentry/tests/unit/test_document_manifest.py`

**Interfaces:**
- Consumes: the manifest from Task 1; `render_manifest` from Task 2.
- Produces: `documents()` driven by the manifest; `NO_ENTRY_DOCUMENTS` removed from the profile.

`documents(model, profile)` currently builds one document per transaction and appends the profile's invented distractors. It becomes: one document per manifest entry, in printed order, `triage` true where the entry names a transaction.

Two consequences to handle deliberately:

**`received_seq` shifts.** It is the order on the desk, and `GUIDED_SEQUENCES` keys off it, so with 26 documents rather than 17 the guidance would attach to different documents. Change `GUIDANCE` and `GUIDED_SEQUENCES` to key by **ref** rather than sequence, so adding a document cannot move the guidance silently. Update `check()` in both profiles accordingly.

**Refs change.** The clinic's pack has no workspaces — verified, zero — so nothing is stranded. Riverbend is untouched by this task and keeps its own `documents()` path until its own decision is taken.

- [ ] **Step 1: Write the failing test**

```python
"""The online set contains what the envelope contains."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "packs" / "alderfinch" / "source.json"


@pytest.fixture
def pack():
    return json.loads(SOURCE.read_text())


def test_the_pack_has_as_many_documents_as_the_envelope(pack):
    """26 printed artefacts, 26 online documents. It was 17."""
    assert len(pack["documents"]) == 26


def test_the_documents_a_student_files_are_in_there(pack):
    """A void cheque, a time card and a petty cash voucher are real judgements. A quotation
    invented for the pack was not one."""
    kinds = {d["kind"] for d in pack["documents"]}

    assert "void_cheque" in kinds
    assert "time_card" in kinds
    assert "petty_cash_voucher" in kinds


def test_the_invented_distractors_are_gone(pack):
    text = json.dumps(pack)

    assert "CV-Q-0118" not in text
    assert "BK-2209" not in text


def test_every_document_carries_a_picture(pack):
    for doc in pack["documents"]:
        for code in ("A", "B", "C"):
            variant = doc["variants"][code]
            assert variant.get("image"), f'{doc["ref"]} {code} has no image'
            assert variant.get("alt", "").strip(), f'{doc["ref"]} {code} has no alt text'


def test_triage_follows_the_manifest(pack):
    """Which documents start a clock is read from the envelope, not decided twice."""
    entered = [d for d in pack["documents"] if pack["answers"]["B"]["triage"][d["ref"]]]

    assert len(entered) == 15, "the clinic has fifteen transactions"
    assert len(pack["documents"]) - len(entered) == 11, "eleven documents are filed, not entered"
```

- [ ] **Step 2: Run it to watch it fail**

Run: `.venv/bin/python -B -m pytest tests/unit/test_document_manifest.py -v -p no:cacheprovider`
Expected: FAIL — the pack has 17 documents, no `kind`, and no images.

- [ ] **Step 3: Rewrite `documents()`**

```python
def documents(model, profile, manifest) -> list[dict]:
    """One document per printed artefact, in the order the envelope holds them.

    It was one per transaction plus distractors the profile invented, which is how the paper
    student came to triage a void cheque and four time cards while the screen student triaged a
    quotation that exists nowhere in the envelope.
    """
    docs = []
    for seq, entry in enumerate(manifest, start=1):
        label = entry["printed_ref"] or entry["kind"].replace("_", " ").capitalize()
        docs.append({
            "ref": entry["ref"],
            "display_ref": f'{label}, {entry["date"]}' if entry["date"] else label,
            "type": "source_document",
            "kind": entry["kind"],
            "date": _iso_date(entry["date"], profile) if entry["date"] else profile.PERIOD["end"],
            "received_seq": seq,
            "guided": entry["ref"] in profile.GUIDANCE,
            "guidance": profile.GUIDANCE.get(entry["ref"]),
            "variants": {},
        })
    return docs
```

`build_source` gains a `--documents DIR` argument naming a directory holding one subdirectory per version (`A/`, `B/`, `C/`), each the output of `gendocs.py` for that version. It takes the inventory from one of them and checks the others against it, reads each artefact's text and renders its picture per version, and fills each variant's `image` and `alt`. Alt text stays what it is today — `f"{display_ref} for {company name}"` — because the text alternative beneath carries the content.

One set cannot stand in for three. The figures printed on the artefact are the whole difference between the versions, which is the only reason three versions exist: D09's receipt reads 810.00 in A, 900.00 in B and 990.00 in C.

Triage becomes `{entry["ref"]: entry["entry_for"] is not None for entry in manifest}` — `txn` is wrong, because a purchase order and its vendor invoice share one — and `expected_entries` maps a transaction to its document by looking up the manifest entry whose `entry_for` matches.

- [ ] **Step 4: Delete the invented distractors**

Remove `NO_ENTRY_DOCUMENTS` from `packs/alderfinch/profile.py` and from `scripts/build_pack.py`. Re-key `GUIDANCE` to refs: `{"D01": "A payment by cheque belongs...", "D02": "Fees charged on account..."}` and `GUIDED_SEQUENCES` becomes `set(GUIDANCE)`. Update `check()` so it validates that every guided ref exists in the manifest.

- [ ] **Step 5: Generate and verify**

```bash
cd ../practicesets && for v in A B C; do PRACTICESET_COMPANY=alderfinch \
  PRACTICESET_OUT=/tmp/clinic/$v .venv/bin/python -B generators/gendocs.py $v; done
cd ../originalentry
.venv/bin/python -B scripts/build_pack.py alderfinch --documents /tmp/clinic \
  > packs/alderfinch/source.json
.venv/bin/python -B -m pytest tests/unit/test_document_manifest.py -v -p no:cacheprovider
```

Then confirm Riverbend is untouched:
```bash
.venv/bin/python -B scripts/build_pack.py riverbend | shasum -a 256
shasum -a 256 packs/riverbend/source.json
```
Both `5a33745ae09902e01eafd61f8e11b37fe31ace0970a7deadc7b636a65f55e308`.

- [ ] **Step 6: Commit**

```bash
git add scripts/build_pack.py packs/alderfinch/ tests/unit/test_document_manifest.py
git commit -m "Give the online student the envelope's documents

The pack carried one document per transaction and two distractors authored into the profile.
The envelope holds a void cheque, four time cards, two petty cash vouchers, an appointment
request and a price list that the online student never saw, and did not hold the quotation and
boarding enquiry the online student was triaging.

Ten triage marks, awarded on each side for a different judgement. The inventory is now read from
what was printed, and guidance is keyed by document rather than by position, so adding a document
cannot move it silently."
```

---

### Task 4: the document is the page

**Files:**
- Modify: `originalentry/templates/student/document.html`
- Modify: `originalentry/tests/integration/test_document_images.py`

`<details>` is already used in three templates, so the disclosure needs no JavaScript — which matters, because `tests/guards/test_javascript.py` guards what the interface may rely on.

The text section must stay **open** when there is no image, or a pack without pictures would show a student nothing.

- [ ] **Step 1: Write the failing test**

Add to `tests/integration/test_document_images.py`:

```python
def test_the_text_is_behind_a_disclosure_when_there_is_a_picture(client, screen_workspace):
    """The document should be the page. The text stays reachable, because an alt attribute
    naming the document tells a screen reader nothing about its figures."""
    body = client.get(_document_url(screen_workspace, "D02")).get_data(as_text=True)

    assert "<details" in body
    assert "View as text" in body
    assert "<details open" not in body


def test_the_text_is_open_when_there_is_no_picture(client, paper_workspace):
    """A pack with no images would otherwise show nothing at all."""
    body = client.get(_document_url(paper_workspace, "D02")).get_data(as_text=True)

    assert "<details open" in body or "<details" not in body
```

- [ ] **Step 2: Run it to watch it fail**

Run: `.venv/bin/python -B -m pytest tests/integration/test_document_images.py -v -p no:cacheprovider`
Expected: FAIL — there is no `<details>` in the template.

- [ ] **Step 3: Change the template**

Replace the opening of the text section:

```jinja
{# The document is the page when there is one. The text is not a fallback — a screen reader
   given only the alt attribute learns the document's name and none of its figures — so it stays
   on the page, one disclosure away, and open when there is no picture to disclose it from. #}
<details class="mb-6" {% if not has_image %}open{% endif %} data-pack-content>
  <summary class="mb-2 text-sm font-semibold cursor-pointer">View as text</summary>
```

and close with `</details>` in place of `</section>`.

- [ ] **Step 4: Run the tests and the guard**

```bash
.venv/bin/python -B -m pytest tests/integration/test_document_images.py tests/guards/ -v -p no:cacheprovider
.venv/bin/python -B -m ruff check originalentry tests scripts
```

- [ ] **Step 5: Commit**

```bash
git add originalentry/templates/student/document.html tests/integration/test_document_images.py
git commit -m "Put the document first

The summary competed with the document for the page. It moves into a disclosure, open when there
is no picture so a pack without images still shows its contents, and native so the page needs no
script to open it."
```

---

### Task 5: build it, validate it, look at it

**Files:** none changed; this is the gate.

- [ ] **Step 1: Build and validate**

```bash
cd ../practicesets && for v in A B C; do PRACTICESET_COMPANY=alderfinch \
  PRACTICESET_OUT=/tmp/clinic/$v .venv/bin/python -B generators/gendocs.py $v; done
cd ../originalentry
.venv/bin/python -B scripts/build_pack.py alderfinch --documents /tmp/clinic > packs/alderfinch/source.json
.venv/bin/python -B scripts/generate_pack.py packs/alderfinch/source.json /tmp/clinic.zip
FLASK_APP=originalentry.app:create_app .venv/bin/python -B -m flask packs validate /tmp/clinic.zip
```

Note: no `--paper` this time, so images are rendered and shipped. Report the archive size and the image count. V12 refuses an image over 2 MB or without alt text; V16 refuses more than 2000 entries or 200 MB.

- [ ] **Step 2: Check the figures did not move**

```bash
.venv/bin/python -B -m pytest tests/unit/test_alderfinch_pack.py -v -p no:cacheprovider
```

The nine checkpoints must still be cp1 7700/7710/7720, cp2 33943.75/34043.75/34143.75, cp3 3210/3300/3390. Adding documents must not touch a figure; if one moves, stop and report.

- [ ] **Step 3: Run the whole suite**

```bash
.venv/bin/python -B -m pytest tests/ -q -p no:cacheprovider
.venv/bin/python -B -m ruff check originalentry tests scripts
```

- [ ] **Step 4: Report, and do not import**

`flask packs import` writes to a shared live Postgres. Report the validate result and stop; the controller decides whether it goes in.

---

## Before a student sees this

- **The clinic's appointment request prints "no accounting entry" in its own footer.** On paper that may be a production marker; on screen it is the answer printed on the question. Read it and decide before this ships.
- **Are the petty cash vouchers and time cards really filed-not-entered?** The vouchers carry accounts and amounts and tie to no transaction; in a set with a replenishment cheque they would support one, and the clinic has none. The printed solution set answers this. The triage key in Task 3 assumes `txn is None` means no entry, and that assumption should be checked rather than inherited.
- **Nobody has worked the clinic through the browser**, with or without pictures.

## Not in this work

- Riverbend, which is live with four versions and students in it, and would go from 31 to 62 documents.
- Thorne & Meadow, which is not online.
- The cheque-stub `if no==18/24/26` literals in `gendocs.py`: dead for both other companies, correct for Riverbend, and a landmine for a fourth.
- `tools/audit.py`, which sees only the `pg`-wrapped artefacts and is blind to 15 of the clinic's 26 and 33 of Riverbend's 62. Worth its own work.
