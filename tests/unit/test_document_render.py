"""A document picture is the document, not a diagram of it."""

from __future__ import annotations

import importlib.util
import os
import shutil
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


def _require_renderer():
    """A sentence rather than an ImportError from inside a module loaded by path.

    The renderer needs WeasyPrint, which is a laptop-only generator dependency, and poppler's
    `pdftoppm`, which is not a Python package at all. Unlike the practice sets these are tooling
    rather than content — a machine without them cannot photograph a document however the suite
    is invoked — so this skips and names what to install, instead of erroring on import, which is
    what it did.
    """
    missing = []
    if importlib.util.find_spec("weasyprint") is None:
        missing.append('WeasyPrint (pip install -e ".[generator]")')
    if shutil.which("pdftoppm") is None:
        missing.append("poppler's pdftoppm (brew install poppler)")
    if missing:
        pytest.skip("the document renderer needs " + " and ".join(missing))


def _clinic_documents(tmp):
    env = dict(os.environ, PRACTICESET_COMPANY="alderfinch", PRACTICESET_OUT=str(tmp))
    subprocess.run([sys.executable, "generators/gendocs.py", "B"],
                   cwd=SETS, env=env, check=True, capture_output=True)
    return Path(tmp)


def test_a_rendered_document_is_a_png_a_student_can_read():
    _require_sets()
    _require_renderer()
    from scripts.render_documents import render_manifest

    with tempfile.TemporaryDirectory() as tmp:
        images = render_manifest(_clinic_documents(tmp))

    assert images, "nothing rendered"
    for ref, data in images.items():
        assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{ref} is not a PNG"
        assert 2_000 < len(data) < 2 * 1024 * 1024, f"{ref} is {len(data)} bytes"


# Darker than this is ink — type, rules and the printed box outline — rather than stock. The
# artefacts print on tinted stock, so "not white" is not a usable test for content.
INK = 160

# The tallest band of blank rows a trimmed document may carry, as a share of its own height.
# Measured on all 26 of the clinic's artefacts: with the {FIT} override the worst is 0.206
# (N06 and N07, the third-sheet vouchers, whose own box padding is most of it), and without it
# twenty of the twenty-six land between 0.393 (D01) and 0.719 (N09). So this sits with 46% of
# headroom under the real renders and 31% of margin over the defect.
MAX_BLANK_BAND = 0.30


def _blank_bands(image) -> list[int]:
    """The runs of rows carrying no ink at all, in pixels, top to bottom."""
    width, height = image.size
    ink = image.convert("L").point(lambda p: 255 if p < INK else 0).tobytes()
    runs, current = [], 0
    for y in range(height):
        if b"\xff" in ink[y * width:(y + 1) * width]:
            if current:
                runs.append(current)
            current = 0
        else:
            current += 1
    if current:
        runs.append(current)
    return runs


def test_the_trim_is_tight_against_the_artefact():
    """The crop reaches the artefact's own box on all four sides.

    This is all it says. It was written claiming it "can't be satisfied by dead space", and it
    can: the dead space is *inside* the artefact's coloured box, so the trimmed edges carry stock
    colour and this passes. Removing the {FIT} override — the exact change it was written to
    catch — passed it 3/3 while five documents shipped at more than double their height, mostly
    empty coloured paper. What sees that is
    test_the_document_is_not_mostly_blank_paper_inside_its_own_box.
    """
    _require_sets()
    _require_renderer()
    import io

    from PIL import Image
    from scripts.render_documents import PAD, render_manifest

    with tempfile.TemporaryDirectory() as tmp:
        images = render_manifest(_clinic_documents(tmp))

    padding = (255, 255, 255)
    for ref, data in images.items():
        im = Image.open(io.BytesIO(data)).convert("RGB")
        w, h = im.size
        top, bottom = PAD, h - PAD - 1
        left, right = PAD, w - PAD - 1
        edges = {
            "top": im.crop((left, top, right, top + 1)),
            "bottom": im.crop((left, bottom, right, bottom + 1)),
            "left": im.crop((left, top, left + 1, bottom)),
            "right": im.crop((right, top, right + 1, bottom)),
        }
        for name, strip in edges.items():
            assert any(p != padding for p in strip.getdata()), \
                f"{ref}: {name} edge is blank padding, not content"


def test_the_document_is_not_mostly_blank_paper_inside_its_own_box():
    """A printed sheet is a fixed height because paper is, so .pg, .half and .third are sized for
    the page rather than for the document; on screen there is no sheet and those heights become
    dead space that no trim can take off, because the box really does occupy it. The {FIT}
    override is what relaxes them, and nothing could see it go: a height cutoff cannot tell a tall
    document from a padded one, and an edge check cannot either, because the dead space is inside
    the artefact's own coloured box and the trimmed edges carry stock colour.

    What does see it is ink. No band of rows carrying no ink may be taller than MAX_BLANK_BAND of
    the document's own height — which catches dead space in the middle of a document as well as
    at its foot, and is a ratio rather than a pixel count, so it does not assume 160 dpi.
    """
    _require_sets()
    _require_renderer()
    import io

    from PIL import Image
    from scripts.render_documents import render_manifest

    with tempfile.TemporaryDirectory() as tmp:
        images = render_manifest(_clinic_documents(tmp))

    assert len(images) == 26, "the clinic prints twenty-six artefacts"
    for ref, data in images.items():
        im = Image.open(io.BytesIO(data))
        widest = max(_blank_bands(im))
        share = widest / im.height
        assert share <= MAX_BLANK_BAND, (
            f"{ref} is {im.height}px tall and carries a {widest}px band with no ink in it "
            f"({share:.0%} of the document). That is a sheet of paper, not a document.")


def test_a_missing_pdftoppm_fails_loudly_rather_than_confusingly(monkeypatch):
    """A guard that can't actually fail isn't a guard. Prove this one fires."""
    from scripts.render_documents import render_manifest

    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(SystemExit, match="poppler"):
        render_manifest(Path("/nonexistent"))


def test_a_missing_weasyprint_fails_loudly_rather_than_confusingly(monkeypatch):
    """The other prerequisite, and the one that was undeclared.

    `from weasyprint import HTML` sat at module scope while WeasyPrint appeared nowhere in
    requirements.txt or pyproject.toml, so a clean checkout that installed the declared
    dependencies could not rebuild the clinic's pack — and the two test modules that render a
    real document errored on *import*, from inside a module build_pack.py loads by path, rather
    than saying what was missing. It is declared under the `generator` extra now, and refused
    here the way pdftoppm already was.
    """
    import builtins

    from scripts.render_documents import render_manifest

    real_import = builtins.__import__

    def refuse(name, *args, **kwargs):
        if name == "weasyprint":
            raise ImportError("No module named 'weasyprint'")
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "weasyprint", raising=False)
    monkeypatch.setattr(builtins, "__import__", refuse)
    with pytest.raises(SystemExit, match="WeasyPrint is not installed") as refused:
        render_manifest(Path("/nonexistent"))

    assert 'pip install -e ".[generator]"' in str(refused.value), "say how to get it"
    assert "Nothing was written" in str(refused.value)


def test_the_renderer_is_skipped_with_a_sentence_rather_than_an_import_error(monkeypatch):
    """_require_renderer is what turns a missing prerequisite into a skip that names it. Prove
    it fires, and names both halves — WeasyPrint is a pip install, pdftoppm is not."""
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(shutil, "which", lambda name: None)

    with pytest.raises(pytest.skip.Exception) as skipped:
        _require_renderer()

    assert "WeasyPrint" in str(skipped.value)
    assert "brew install poppler" in str(skipped.value)
