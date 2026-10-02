"""The photographs on disk reach the zip, as the right version's photograph.

``scripts/generate_pack.py``'s ``_load_photographs`` is the only thing that turns the per-version
PNGs the translator wrote into the ``{(ref, code): bytes}`` dict ``build()`` consumes. The two
halves were tested and the join was not: ``return {}`` at the top of it left 43 tests passing,
while every student silently went back to being shown a Pillow drawing instead of a photograph of
their own document — which is the whole point of the branch — and ``flask packs validate`` still
reported ``Valid.`` with 78 images, because it counts images without caring how they were made.

So this goes the whole way: PNG on disk, through ``main()``, out of the finished archive.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import struct
import zlib
from pathlib import Path

from originalentry.packs.zip_reader import read_pack_zip

from tests.packs import testco_alpha_source

ROOT = Path(__file__).resolve().parents[2]


def _generate_pack():
    """``scripts`` is not a package, so the module is loaded by path."""
    spec = importlib.util.spec_from_file_location(
        "generate_pack", ROOT / "scripts" / "generate_pack.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _png(red: int, green: int, blue: int, size: int = 6) -> bytes:
    """A real single-colour PNG. The colour is what makes one photograph tellable from another."""

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + kind + payload
                + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + bytes((red, green, blue)) * size for _ in range(size))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _two_version_source() -> dict:
    """The fixture authoring source with a second version added.

    One version could not show this: the point is that version B's photograph goes to version B
    and nowhere else, and with a single version there is nothing for it to go wrong onto.
    """
    source = copy.deepcopy(testco_alpha_source.SOURCE)
    source["variants"] = [*source["variants"], {"code": "B", "label": "Variant B", "drivers": {}}]
    source["opening_balances"]["B"] = copy.deepcopy(source["opening_balances"]["A"])
    source["answers"]["B"] = copy.deepcopy(source["answers"]["A"])
    for document in source["documents"]:
        document["variants"]["B"] = copy.deepcopy(document["variants"]["A"])
    return source


def test_the_photographs_beside_the_source_are_the_images_in_the_zip(tmp_path):
    """Written to documents/B/, served as version B's, and version A is untouched by it."""
    sentinel = _png(12, 34, 56)
    (tmp_path / "source.json").write_text(json.dumps(_two_version_source()))
    photographs = tmp_path / "documents" / "B"
    photographs.mkdir(parents=True)
    (photographs / "INV-1.png").write_bytes(sentinel)
    out = tmp_path / "pack.zip"

    assert _generate_pack().main([str(tmp_path / "source.json"), str(out)]) == 0

    images = read_pack_zip(out.read_bytes()).images
    assert images["documents/B/INV-1.png"] == sentinel, (
        "version B's photograph did not reach the zip; a drawn image shipped in its place")
    assert images["documents/A/INV-1.png"] != sentinel, (
        "version A was served version B's photograph, which is the defect (ref, code) keying "
        "exists to prevent")


def test_a_photograph_for_one_document_does_not_become_every_document_s(tmp_path):
    """The key is a pair, so INV-2 has no photograph of its own and must not inherit INV-1's."""
    sentinel = _png(200, 10, 10)
    (tmp_path / "source.json").write_text(json.dumps(_two_version_source()))
    photographs = tmp_path / "documents" / "B"
    photographs.mkdir(parents=True)
    (photographs / "INV-1.png").write_bytes(sentinel)
    out = tmp_path / "pack.zip"

    assert _generate_pack().main([str(tmp_path / "source.json"), str(out)]) == 0

    images = read_pack_zip(out.read_bytes()).images
    assert images["documents/B/INV-1.png"] == sentinel
    assert images["documents/B/INV-2.png"] != sentinel


def test_a_paper_pack_carries_no_photographs_at_all(tmp_path):
    """--paper is the paper student's pack: the photographs on disk are not smuggled into it."""
    (tmp_path / "source.json").write_text(json.dumps(_two_version_source()))
    photographs = tmp_path / "documents" / "B"
    photographs.mkdir(parents=True)
    (photographs / "INV-1.png").write_bytes(_png(12, 34, 56))
    out = tmp_path / "pack.zip"

    assert _generate_pack().main(
        [str(tmp_path / "source.json"), str(out), "--paper"]) == 0

    assert read_pack_zip(out.read_bytes()).images == {}
