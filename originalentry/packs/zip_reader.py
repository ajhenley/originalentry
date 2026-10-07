"""Opening a pack zip, and refusing a bad one (T5.1, V16).

This module reads the archive the generator produced and nothing more. It touches no database, so
every refusal here is about the file itself: a path that escapes the archive, an archive that
would unpack to more than a teaching pack ever needs, a missing or unreadable pack.json.

The limits are deliberately modest. A pack is a chart of accounts, a few dozen documents and their
images — anything larger is a mistake or an attack, and either way the instructor should hear
about it before the upload reaches the database.
"""

from __future__ import annotations

import hashlib
import io
import json
import posixpath
import zipfile
from dataclasses import dataclass, field

MAX_ENTRIES = 2000
MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
PACK_NAME = "pack.json"
KEYS_PREFIX = "answer_keys/"
DOCUMENTS_PREFIX = "documents/"


class PackZipRefused(Exception):
    """The archive is not one this app will open. The message names the file at fault."""


@dataclass
class PackBundle:
    pack: dict
    keys: dict[str, dict] = field(default_factory=dict)
    images: dict[str, bytes] = field(default_factory=dict)  # "documents/A/INV-1.png" -> bytes
    sha256: str = ""


def read_pack_zip(fileobj) -> PackBundle:
    data = fileobj.read() if hasattr(fileobj, "read") else fileobj
    digest = hashlib.sha256(data).hexdigest()

    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise PackZipRefused("That file is not a zip archive.") from exc

    infos = archive.infolist()
    if len(infos) > MAX_ENTRIES:
        raise PackZipRefused(
            f"That archive holds {len(infos)} files; the limit is {MAX_ENTRIES}."
        )
    # A cheap early reject on the declared sizes. It is not the real guard -- ``file_size`` is
    # attacker-controlled central-directory metadata and a zip bomb can declare it small -- so the
    # bytes actually decompressed are counted against the same budget as each member is read below.
    total = sum(info.file_size for info in infos)
    if total > MAX_UNCOMPRESSED_BYTES:
        raise PackZipRefused(
            "That archive would unpack to more than "
            f"{MAX_UNCOMPRESSED_BYTES // (1024 * 1024)} MB."
        )
    for info in infos:
        _refuse_unsafe_path(info.filename)

    names = {info.filename for info in infos if not info.is_dir()}
    if PACK_NAME not in names:
        raise PackZipRefused("That archive has no pack.json at its root.")

    remaining = [MAX_UNCOMPRESSED_BYTES]

    def _capped_read(name: str) -> bytes:
        """Decompress one member in bounded chunks, stopping the moment the cumulative output
        would exceed the budget -- so a member whose true size dwarfs its declared one cannot fill
        memory before the size check ever runs."""
        chunks: list[bytes] = []
        with archive.open(name) as member:
            while True:
                chunk = member.read(65536)
                if not chunk:
                    break
                remaining[0] -= len(chunk)
                if remaining[0] < 0:
                    raise PackZipRefused(
                        "That archive unpacks to more than "
                        f"{MAX_UNCOMPRESSED_BYTES // (1024 * 1024)} MB."
                    )
                chunks.append(chunk)
        return b"".join(chunks)

    bundle = PackBundle(pack=_load_json(PACK_NAME, _capped_read(PACK_NAME)), sha256=digest)
    for name in sorted(names):
        if name.startswith(KEYS_PREFIX) and name.endswith(".json"):
            variant = posixpath.basename(name)[: -len(".json")]
            bundle.keys[variant] = _load_json(name, _capped_read(name))
        elif name.startswith(DOCUMENTS_PREFIX) and name.endswith(".png"):
            bundle.images[name] = _capped_read(name)
    return bundle


def _refuse_unsafe_path(name: str) -> None:
    if name.startswith("/") or name.startswith("\\") or ":" in name.split("/")[0][1:2]:
        raise PackZipRefused(f"{name} is an absolute path.")
    normalised = posixpath.normpath(name)
    if normalised.startswith("../") or normalised == ".." or normalised.startswith("/"):
        raise PackZipRefused(f"{name} points outside the archive.")


def _load_json(name: str, data: bytes) -> dict:
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PackZipRefused(f"{name} is not readable JSON.") from exc
