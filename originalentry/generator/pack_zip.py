"""Write a :class:`GeneratedPack` to the zip the app imports (T5.1).

Layout, matching ``packs/zip_reader.py``:

    pack.json
    answer_keys/<variant>.json
    documents/<variant>/<ref>.png     # omitted for a paper pack
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import io
import json
import zipfile
from pathlib import Path

from .build import GeneratedPack


def _json_default(obj):
    if isinstance(obj, _dt.date):
        return obj.isoformat()
    raise TypeError(f"not JSON-serialisable: {type(obj).__name__}")


def to_bytes(generated: GeneratedPack) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("pack.json", json.dumps(generated.pack, indent=2, default=_json_default))
        for code, key in sorted(generated.keys.items()):
            archive.writestr(
                f"answer_keys/{code}.json", json.dumps(key, indent=2, default=_json_default)
            )
        for path, data in sorted(generated.images.items()):
            archive.writestr(path, data)
    return buffer.getvalue()


def write_zip(generated: GeneratedPack, out_path: str | Path | None = None) -> tuple[bytes, str]:
    """Return ``(zip_bytes, sha256)`` and, if ``out_path`` is given, write the bytes there."""
    data = to_bytes(generated)
    digest = hashlib.sha256(data).hexdigest()
    if out_path is not None:
        Path(out_path).write_bytes(data)
    return data, digest
