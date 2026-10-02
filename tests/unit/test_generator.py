"""The pack generator (T5): it computes the answers from the authored transactions, strips its
author-only fields, renders images, and produces a zip the reader accepts. A generated pack's
figures must equal the hand-written finished pack, and a broken source is refused with problems.
"""

import copy
import io
import json
from pathlib import Path

import pytest
from originalentry.generator import GeneratorError, build, write_zip
from originalentry.packs.zip_reader import read_pack_zip
from PIL import Image

from tests.packs import testco_alpha, testco_alpha_source

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

ALDERFINCH_SOURCE = Path(__file__).resolve().parents[2] / "packs" / "alderfinch" / "source.json"


def _a_tiny_png(colour=(255, 0, 0)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (1, 1), colour).save(buf, format="PNG")
    return buf.getvalue()


def test_computes_the_same_figures_as_the_finished_pack():
    generated = build(testco_alpha_source.SOURCE)
    key = generated.keys["A"]
    finished = testco_alpha.KEY_A["expected_balances"]
    assert key["expected_balances"]["adjusted"] == finished["adjusted"]
    assert key["expected_balances"]["post_closing"] == finished["post_closing"]
    assert key["checkpoints"] == {"cp1": 500000}


def test_strips_author_only_fields_from_pack():
    generated = build(testco_alpha_source.SOURCE)
    assert "answers" not in generated.pack
    assert all("measure" not in c for c in generated.pack["checkpoints"])


def test_paper_pack_has_no_images():
    generated = build(testco_alpha_source.SOURCE, render_images=False)
    assert generated.images == {}
    for document in generated.pack["documents"]:
        for variant in document["variants"].values():
            assert variant.get("image") is None


def test_renders_a_png_per_document_per_variant():
    generated = build(testco_alpha_source.SOURCE, render_images=True)
    assert set(generated.images) == {"documents/A/INV-1.png", "documents/A/INV-2.png"}
    for data in generated.images.values():
        assert data.startswith(PNG_SIGNATURE)
    # Each document variant now points at its image and has alt text (V12).
    inv1 = generated.pack["documents"][0]["variants"]["A"]
    assert inv1["image"] == "documents/A/INV-1.png"
    assert inv1["alt"]


def test_zip_round_trips_through_the_reader():
    generated = build(testco_alpha_source.SOURCE, render_images=True)
    data, digest = write_zip(generated)
    bundle = read_pack_zip(io.BytesIO(data))
    assert bundle.pack["company"]["slug"] == "testco-alpha"
    assert set(bundle.keys) == {"A"}
    assert set(bundle.images) == {"documents/A/INV-1.png", "documents/A/INV-2.png"}
    assert bundle.sha256 == digest


def test_refuses_openings_that_do_not_balance():
    bad = copy.deepcopy(testco_alpha_source.SOURCE)
    bad["opening_balances"]["A"]["accounts"]["101"] += 1  # no longer sums to zero (V6)
    with pytest.raises(GeneratorError) as exc:
        build(bad)
    assert any(p.rule == "V6" for p in exc.value.problems)


def test_a_supplied_photograph_is_not_drawn_over():
    """The drawn renderer is for packs with no printed artefact. A pack that ships photographs
    of the real documents had them overwritten at zip time, and validated and shipped looking
    exactly as it did before."""
    source = json.loads(ALDERFINCH_SOURCE.read_text())
    ref = source["documents"][0]["ref"]
    sentinels = {("A", (255, 0, 0)), ("B", (0, 255, 0)), ("C", (0, 0, 255))}
    supplied = {(ref, code): _a_tiny_png(colour) for code, colour in sentinels}

    generated = build(source, render_images=True, images=supplied)

    for (_ref, code), sentinel in supplied.items():
        assert generated.images[f"documents/{code}/{ref}.png"] == sentinel


def test_each_version_gets_its_own_photograph():
    """One photograph per ref was handed to every version, so a version-A student was shown
    version B's document — and the figures on it are the whole difference between the versions."""
    source = json.loads(ALDERFINCH_SOURCE.read_text())
    ref = source["documents"][0]["ref"]
    supplied = {(ref, "B"): _a_tiny_png((0, 255, 0))}

    generated = build(source, render_images=True, images=supplied)

    assert generated.images[f"documents/B/{ref}.png"] == supplied[(ref, "B")]
    for code in ("A", "C"):
        assert generated.images[f"documents/{code}/{ref}.png"] != supplied[(ref, "B")], \
            f"version {code} was given version B's photograph"


def test_refuses_missing_triage():
    bad = copy.deepcopy(testco_alpha_source.SOURCE)
    del bad["answers"]["A"]["triage"]["INV-2"]  # a document with no triage value (V10)
    with pytest.raises(GeneratorError) as exc:
        build(bad)
    assert any(p.rule == "V10" for p in exc.value.problems)
