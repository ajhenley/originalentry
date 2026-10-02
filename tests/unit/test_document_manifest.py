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
