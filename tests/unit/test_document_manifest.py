"""The online set contains what the envelope contains, in the student's own version.

These tests build the pack. They used to read the committed ``packs/alderfinch/source.json`` and
the committed PNGs beside it, and nothing rebuilt either — so they asserted about an artefact
rather than about the code that produces it, and would have ratified any generator at all. Triage
was changed to read the wrong field and the whole PNG-writing block was deleted, and eighteen of
eighteen tests still passed.

So: ``gendocs.py`` runs here, for all three versions, into a temporary directory; the translator
runs against that; and everything below asserts on what came out.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PRACTICESETS = ROOT.parent / "practicesets"
ALLOW_NO_SETS = os.environ.get("PACK_TRANSLATOR_ALLOW_NO_SETS") == "1"

CODES = ("A", "B", "C")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# "810.00", "1,480.00". Two decimal places, so an hour count ("8.0") and a time ("12:01") are not
# money and a discount ("2/10, n/30") is not either.
MONEY = re.compile(r"\d{1,3}(?:,\d{3})*\.\d{2}")
# The printed footer, which names the version. The text alternative drops it on purpose.
FOOTER = re.compile(r'<div class="foot">.*?</div>', re.S)
TAGS = re.compile(r"<[^>]+>")


def _require_sets():
    """Absence of the practice sets fails rather than skips.

    Nothing here can run without the sibling checkout, and left as a skip the whole module
    vanishes in any environment without it — which is every CI run this repository has — and the
    suite reports green having tested nothing. Opting out is deliberate and has to be spelled.
    """
    if PRACTICESETS.is_dir():
        return
    if ALLOW_NO_SETS:
        pytest.skip("PACK_TRANSLATOR_ALLOW_NO_SETS=1")
    pytest.fail(
        f"The practice sets are not at {PRACTICESETS}, so the tests that build the clinic's pack "
        f"from its own printed envelope cannot run. Check practicesets out beside this repository, "
        f"or set PACK_TRANSLATOR_ALLOW_NO_SETS=1 to accept the gap knowingly."
    )


def _script():
    """scripts/ is not a package, so the module is loaded by path."""
    spec = importlib.util.spec_from_file_location(
        "build_pack", ROOT / "scripts" / "build_pack.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def envelope(tmp_path_factory):
    """The printed envelope, three times over: one directory per version, as gendocs.py
    writes it."""
    _require_sets()
    out = tmp_path_factory.mktemp("clinic")
    for code in CODES:
        env = dict(os.environ, PRACTICESET_COMPANY="alderfinch",
                   PRACTICESET_OUT=str(out / code))
        subprocess.run([sys.executable, "generators/gendocs.py", code],
                       cwd=PRACTICESETS, env=env, check=True, capture_output=True)
    return out


@pytest.fixture(scope="module")
def built(envelope, tmp_path_factory):
    """The translator's own output for that envelope, pictures and all. Built once: rendering
    seventy-eight documents through WeasyPrint and poppler is the slow part of this module."""
    pictures = tmp_path_factory.mktemp("photographs")
    source = _script().build_source("alderfinch", PRACTICESETS,
                                    documents_dir=envelope, images_dir=pictures)
    return source, pictures


@pytest.fixture(scope="module")
def pack(built):
    return built[0]


@pytest.fixture(scope="module")
def photographs(built):
    return built[1]


def _manifest(envelope, code="B"):
    return json.loads((envelope / code / "manifest.json").read_text())


def _printed_money(markup: str) -> set[str]:
    """Every money figure on the document, read off the raw html rather than through the
    translator's own reader, so the two cannot agree by sharing a bug. The footer is removed
    because the text alternative drops it, deliberately, to keep the version marker off the page.
    """
    return set(MONEY.findall(TAGS.sub(" ", FOOTER.sub("", markup))))


def test_the_pack_has_as_many_documents_as_the_envelope(pack, envelope):
    """26 printed artefacts, 26 online documents. It was 17."""
    assert len(pack["documents"]) == 26
    assert [d["ref"] for d in pack["documents"]] == [e["ref"] for e in _manifest(envelope)]


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


def test_triage_follows_the_manifest(pack, envelope):
    """Which documents start a clock is read from the envelope, and from ``entry_for`` rather than
    ``txn``: a purchase order and its vendor invoice share a transaction and only the invoice is
    the evidence a student journalises from."""
    manifest = {e["ref"]: e for e in _manifest(envelope)}
    triage = pack["answers"]["B"]["triage"]
    entered = [ref for ref, start in triage.items() if start]

    assert len(entered) == 15, "the clinic has fifteen transactions"
    assert len(pack["documents"]) - len(entered) == 11, "eleven documents are filed, not entered"
    for ref, entry in manifest.items():
        assert triage[ref] == (entry["entry_for"] is not None), ref
    # The pair that tells the two fields apart: both belong to transaction 3.
    assert triage["D03"] is False, "the purchase order is filed"
    assert triage["D03-2"] is True, "its vendor invoice is the entry"


def test_every_version_has_its_own_photograph(pack, photographs):
    """One photograph per ref served all three versions, so a version-A student read version B's
    receipt. Images are not embedded in source.json — that is not where this pack format keeps
    them (PackAsset and V12 expect them in the zip) — so they sit on disk beside it, per version.
    """
    for doc in pack["documents"]:
        for code in CODES:
            png = photographs / code / f'{doc["ref"]}.png'
            assert png.is_file(), f'{doc["ref"]} has no version-{code} photograph at {png}'
            assert png.read_bytes()[:8] == PNG_SIGNATURE, f'{doc["ref"]} {code} is not a PNG'


def test_the_photograph_differs_where_the_figure_differs(photographs):
    """D09's receipt reads 810.00 in A, 900.00 in B and 990.00 in C, and the picture is the whole
    document. Three identical files would mean two versions are being shown the third's money."""
    shots = {code: (photographs / code / "D09.png").read_bytes() for code in CODES}

    assert len(set(shots.values())) == 3, "D09's three versions are not three pictures"


def test_the_text_a_student_reads_is_the_document_they_are_shown(pack, envelope):
    """The invariant that would have caught both of the figure defects at once.

    For every document and every version, each money figure in the text alternative is on that
    version's document, and each money figure on the document is in the text. Built from the
    transaction instead, D03's text carried its vendor invoice's 1,480.00 while its own photograph
    showed a purchase order, and nine documents carried no figures at all.
    """
    file_of = {e["ref"]: e["file"] for e in _manifest(envelope)}
    for doc in pack["documents"]:
        for code in CODES:
            said = set(MONEY.findall(json.dumps(doc["variants"][code]["text_alternative"])))
            printed = _printed_money((envelope / code / file_of[doc["ref"]]).read_text())
            assert said == printed, (
                f'{doc["ref"]} version {code}: the text says {sorted(said - printed) or "nothing"} '
                f'that the document does not, and the document says '
                f'{sorted(printed - said) or "nothing"} that the text does not')


def test_no_document_is_a_blank_page(pack):
    """Nine artefacts belonged to no transaction and shipped ``{"B": {}}`` — the void cheque, four
    time cards, two petty cash vouchers, the appointment request and the price list. All nine
    carried a triage mark, and a paper-mode student or a screen-reader user had nothing to triage.
    """
    for doc in pack["documents"]:
        for code in CODES:
            text = doc["variants"][code].get("text_alternative") or {}
            assert text.get("fields") or text.get("lines"), \
                f'{doc["ref"]} version {code} has no text at all'


def test_a_purchase_order_does_not_read_as_its_vendor_invoice(pack):
    """D03 and D03-2 are two different pieces of paper about one transaction. The one a student is
    told to file carried the other's text byte-identically, down to "Vendor inv CV-3310"."""
    by_ref = {d["ref"]: d for d in pack["documents"]}
    order = by_ref["D03"]["variants"]["B"]["text_alternative"]
    invoice = by_ref["D03-2"]["variants"]["B"]["text_alternative"]

    assert order != invoice
    assert "PURCHASE ORDER" in json.dumps(order)
    assert "CV-3310" not in json.dumps(order), "the order is not the invoice"
    assert "CV-3310" in json.dumps(invoice)


def test_the_text_does_not_say_which_version_a_student_holds(pack):
    """The printed footer says "… · version B". Read off the document, the text would leak it, and
    a student who can name their version can find someone holding the same one."""
    for doc in pack["documents"]:
        for code in CODES:
            text = json.dumps(doc["variants"][code]["text_alternative"])
            for leak in ("version A", "version B", "version C"):
                assert leak not in text, f'{doc["ref"]} {code} says "{leak}"'


def test_a_document_is_listed_as_what_it_is(pack):
    """``display_ref`` was the bare printed reference — "4104", "18", "J. Finch" — so a void cheque
    could not be told from the three real ones in a list of twenty-six. It is composed from the
    kind and the reference, in the vocabulary the old labels used ("Check 4101", "Invoice 7101").
    """
    listed = {d["ref"]: d["display_ref"] for d in pack["documents"]}

    assert listed["N01"] == "Void cheque 4104"
    assert listed["N06"] == "Petty cash voucher 18"
    assert listed["N02"] == "Time card, J. Finch"
    assert listed["D01"] == "Check 4101"
    assert listed["D02"] == "Invoice 7101"
    assert listed["D03"] == "Purchase order AF-0440"
    assert listed["D03-2"] == "Vendor invoice CV-3310"
    assert listed["D15"] == "Payroll register"
    assert len(set(listed.values())) == len(listed), "two documents are listed the same way"


def test_a_document_is_dated_as_it_is_printed(pack):
    """Four artefacts belong to no transaction and state a date of their own. The manifest has none
    for them and the period's last day stood in, so the void cheque printed Dec 6 and was listed
    Dec 7. A time card states a period and a price list takes effect in January; neither is
    guessed at, and both still fall back to the period end.
    """
    dated = {d["ref"]: d["date"] for d in pack["documents"]}

    assert dated["N01"] == "2026-12-06", "the void cheque's own stub says Dec 6"
    assert dated["N06"] == "2026-12-02"
    assert dated["N07"] == "2026-12-04"
    assert dated["N08"] == "2026-12-06"
    for ref in ("N02", "N03", "N04", "N05", "N09"):
        assert dated[ref] == "2026-12-07", f"{ref} states no date, so the period ends it"


def test_the_remittance_names_the_number_printed_on_it(pack):
    """D04 was labelled "20714" while its text said "Remittance 7091" — a number printed nowhere
    on the artefact. Both now come from the document itself."""
    d04 = next(d for d in pack["documents"] if d["ref"] == "D04")
    text = json.dumps(d04["variants"]["B"]["text_alternative"])

    assert d04["display_ref"] == "Remittance 20714"
    assert "20714" in text
    assert "7091" not in text


def test_d09_reads_its_own_version_in_text_and_in_picture(pack, photographs, envelope):
    """The defect, stated as a test. D09's answer key is 810.00 for A, 900.00 for B and 990.00 for
    C; a version-A student shown B's picture records 900 and fails checkpoints 2 and 3."""
    expected = {"A": "810.00", "B": "900.00", "C": "990.00"}
    d09 = next(d for d in pack["documents"] if d["ref"] == "D09")

    for code, figure in expected.items():
        said = set(MONEY.findall(json.dumps(d09["variants"][code]["text_alternative"])))
        assert said == {figure}, f"version {code}'s text says {sorted(said)}, not {figure}"
        printed = _printed_money((envelope / code / "documents" / "D09.html").read_text())
        assert printed == {figure}, f"version {code}'s document says {sorted(printed)}"
        assert (photographs / code / "D09.png").is_file()


def test_the_versions_must_print_the_same_envelope(envelope, tmp_path):
    """One version's inventory stands for all three, which is only safe because the others are
    checked against it. Prove the check fires rather than trusting that it would."""
    script = _script()
    for code in CODES:
        (tmp_path / code).mkdir()
        (tmp_path / code / "manifest.json").write_text(
            (envelope / code / "manifest.json").read_text())
    diverged = json.loads((tmp_path / "C" / "manifest.json").read_text())
    diverged[0]["entry_for"] = None          # version C no longer journalises its first invoice
    (tmp_path / "C" / "manifest.json").write_text(json.dumps(diverged))

    with pytest.raises(SystemExit) as caught:
        script.build_source("alderfinch", PRACTICESETS, documents_dir=tmp_path)

    assert "inventory" in str(caught.value)
    assert "Nothing was written" in str(caught.value)


def test_one_set_of_documents_is_refused(envelope, tmp_path):
    """``--documents`` naming a single gendocs.py output is how every student came to be shown
    version B. It is not silently accepted as version B's."""
    script = _script()
    (tmp_path / "manifest.json").write_text((envelope / "B" / "manifest.json").read_text())

    with pytest.raises(SystemExit) as caught:
        script.build_source("alderfinch", PRACTICESETS, documents_dir=tmp_path)

    assert "one directory per version" in str(caught.value)
    assert "Nothing was written" in str(caught.value)
