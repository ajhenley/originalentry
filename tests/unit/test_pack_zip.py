"""Reading a pack zip, and refusing a bad one (T5.1, T5.4 V16).

A pack arrives as a zip the generator made. This module opens it and nothing more: it does not
touch the database, so every refusal here is about the file itself — a path that escapes the
archive, an archive that would fill the disk, a missing pack.json.
"""

import io
import json
import zipfile

import pytest
from parchment.packs.zip_reader import (
    MAX_ENTRIES,
    MAX_UNCOMPRESSED_BYTES,
    PackZipRefused,
    read_pack_zip,
)

from tests.packs import testco_alpha


def _zip(entries: dict[str, bytes | str]) -> io.BytesIO:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    buffer.seek(0)
    return buffer


def _good_zip() -> io.BytesIO:
    return _zip({
        "pack.json": json.dumps(testco_alpha.PACK),
        "answer_keys/A.json": json.dumps(testco_alpha.KEY_A),
    })


def test_a_pack_and_its_keys_come_back_together():
    bundle = read_pack_zip(_good_zip())

    assert bundle.pack["company"]["slug"] == "testco-alpha"
    assert set(bundle.keys) == {"A"}
    assert bundle.keys["A"]["variant"] == "A"
    assert len(bundle.sha256) == 64


def test_the_checksum_follows_the_bytes():
    first = read_pack_zip(_good_zip()).sha256
    second = read_pack_zip(_good_zip()).sha256
    third = read_pack_zip(_zip({"pack.json": json.dumps(testco_alpha.PACK)})).sha256

    assert first == second
    assert first != third


def test_a_zip_without_a_pack_is_refused():
    with pytest.raises(PackZipRefused) as refused:
        read_pack_zip(_zip({"answer_keys/A.json": "{}"}))

    assert "pack.json" in str(refused.value)


def test_a_path_that_escapes_the_archive_is_refused():
    for path in ("../pack.json", "/etc/pack.json", "documents/../../pack.json"):
        with pytest.raises(PackZipRefused):
            read_pack_zip(_zip({path: "{}", "pack.json": json.dumps(testco_alpha.PACK)}))


def test_an_archive_with_too_many_entries_is_refused():
    entries = {f"documents/A/DOC-{i}.png": b"x" for i in range(MAX_ENTRIES + 1)}
    entries["pack.json"] = json.dumps(testco_alpha.PACK)

    with pytest.raises(PackZipRefused):
        read_pack_zip(_zip(entries))


def test_an_archive_that_would_unpack_to_too_much_is_refused():
    """A zip bomb is small on disk and enormous once opened, so the declared size is checked."""
    padding = b"0" * (MAX_UNCOMPRESSED_BYTES + 1)

    with pytest.raises(PackZipRefused):
        read_pack_zip(_zip({"pack.json": json.dumps(testco_alpha.PACK),
                            "documents/A/big.png": padding}))


def test_a_file_that_is_not_json_is_refused_by_name():
    with pytest.raises(PackZipRefused) as refused:
        read_pack_zip(_zip({"pack.json": "{not json", "answer_keys/A.json": "{}"}))

    assert "pack.json" in str(refused.value)
