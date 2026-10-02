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
    """A height cutoff can't tell a tall document from a padded one — a third-sheet voucher on
    coloured stock passed one at 778px while two thirds of it was dead space inside its own box.
    What actually says the trim is tight is that content reaches every edge of the trimmed area:
    the first and last row and column just inside the white margin must carry ink or stock
    colour, never blank padding. That can't be satisfied by dead space."""
    _require_sets()
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


def test_a_missing_pdftoppm_fails_loudly_rather_than_confusingly(monkeypatch):
    """A guard that can't actually fail isn't a guard. Prove this one fires."""
    import shutil

    from scripts.render_documents import render_manifest

    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(SystemExit, match="poppler"):
        render_manifest(Path("/nonexistent"))
