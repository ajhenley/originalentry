"""Turn each printed artefact into the picture a student sees.

The document a student reads on screen should be the document a student on paper holds, so this
renders the paper set's own html through the paper set's own stylesheet. It does not draw a
document; it photographs one.

WeasyPrint dropped PNG output, so the path is html to pdf to raster. The page is auto-sized and
then trimmed, because a half-sheet artefact rendered onto a full page is mostly white paper.

Pack building is laptop-only, same as Pillow, but needs one more thing on the path: poppler's
`pdftoppm` (`brew install poppler`) does the PDF-to-PNG rasterising, because this machine's Python
cannot install a wheel to do it instead.

Both prerequisites are stated in the README's "Building a pack" section. WeasyPrint is declared
under the `generator` extra in pyproject.toml; pdftoppm cannot be, so `render_manifest` refuses
with the command that installs it.
"""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageChops

PAD = 18             # white margin left around the trimmed document


def _weasyprint() -> type:
    """WeasyPrint's ``HTML``, or a sentence saying how to get it.

    Imported here rather than at module scope. WeasyPrint is a laptop-only generator dependency,
    and at module scope a machine without it got an ImportError from inside a module that
    ``build_pack.py`` loads by path — so ``test_document_render.py`` and
    ``test_document_manifest.py`` **errored on import** instead of saying what was missing. This
    is the care ``render_manifest`` already takes over ``pdftoppm``, which cannot be declared as a
    Python dependency at all.
    """
    try:
        from weasyprint import HTML
    except ImportError as missing:          # pragma: no cover - depends on the machine
        raise SystemExit(
            "WeasyPrint is not installed, so a document cannot be rendered. It is a pack-generator "
            'dependency: pip install -e ".[generator]". Nothing was written.') from missing
    return HTML


# A printed sheet is a fixed height because paper is, so .pg, .half and .third are sized for
# the page rather than for the document. On screen there is no sheet, and those heights become
# dead space inside the document's own box, which no trim can take off because the box really
# does occupy it. Only the single-document render relaxes them; the paper set is untouched.
FIT = """
.pg, .half, .third { height: auto !important; min-height: 0 !important;
                     page-break-after: auto !important }
.foot { position: static !important; margin-top: 14px }
"""


def render_png(fragment: str, css: str) -> bytes:
    document = (f"<!DOCTYPE html><html><head><meta charset='utf-8'><style>{css}\n"
                f"@page {{ size: auto; margin: 0 }} body {{ margin: 0 }}\n{FIT}"
                f"</style></head><body>{fragment}</body></html>")

    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = Path(tmp) / "doc.pdf"
        _weasyprint()(string=document).write_pdf(pdf_path)
        # WeasyPrint dropped PNG output at v53, so the raster comes from poppler. -r is dots per
        # inch against a 72dpi PDF, so 160 renders a 750pt-wide invoice at about 1650px: legible
        # when a student zooms, and still well inside the 2 MB a pack image may weigh.
        subprocess.run(["pdftoppm", "-png", "-r", "160", "-singlefile",
                        str(pdf_path), str(Path(tmp) / "page")], check=True, capture_output=True)
        image = Image.open(Path(tmp) / "page.png").convert("RGB")

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
    if shutil.which("pdftoppm") is None:
        raise SystemExit(
            "pdftoppm is not on the path, so a document cannot be rendered. It comes with poppler: "
            "brew install poppler. Nothing was written.")
    # Both prerequisites, before the first render rather than on the first document: a build that
    # is going to refuse should refuse having written nothing.
    _weasyprint()

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
