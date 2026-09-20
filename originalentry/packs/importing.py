"""Taking a pack zip into the catalogue (I1.7, T5.5).

Validation happens before anything is written, and the refusal carries **every** problem with its
JSON path — an instructor fixing a pack should not have to upload it eight times to find eight
mistakes.

Two rules can only be checked here, because they are about what the app already holds (V14): the
same archive cannot arrive twice, and a version must be newer than every version of that company
already in the catalogue. A pack version is immutable once a workspace pins it, so a correction is
always a new version, never an edit.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import ContentPack, PackAsset, PackVersion
from ..services import staff_actions
from . import schema
from .importer import import_answer_keys, import_content
from .validate import Problem, validate_pack
from .zip_reader import PackZipRefused, read_pack_zip

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_IMAGE_BYTES = 2 * 1024 * 1024


@dataclass
class PackImportRefused(Exception):
    """Nothing was written. ``problems`` names each one, with the path it was found at."""

    problems: list[Problem]

    def __str__(self) -> str:
        return "; ".join(f"{p.path}: {p.message}" for p in self.problems)


def import_pack_zip(session: Session, fileobj, actor=None) -> PackVersion:
    try:
        bundle = read_pack_zip(fileobj)
    except PackZipRefused as refused:
        raise PackImportRefused([Problem("archive", "V16", str(refused))]) from refused

    try:
        pack = schema.load_pack(bundle.pack)
    except ValidationError as invalid:
        raise PackImportRefused(_from_pydantic("pack.json", invalid)) from invalid

    keys: dict[str, schema.AnswerKey] = {}
    problems: list[Problem] = []
    for code, payload in bundle.keys.items():
        try:
            keys[code] = schema.load_answer_key(payload)
        except ValidationError as invalid:
            problems.extend(_from_pydantic(f"answer_keys/{code}.json", invalid))
    if problems:
        raise PackImportRefused(problems)

    problems = list(validate_pack(pack, keys or None))
    problems.extend(_v12_images(pack, bundle))
    problems.extend(_v14_catalogue(session, pack, bundle.sha256))
    if problems:
        raise PackImportRefused(problems)

    version = import_content(session, pack, source_sha256=bundle.sha256)
    if keys:
        import_answer_keys(session, version, keys)
    _store_images(session, version, pack, bundle)
    staff_actions.record(
        session, actor, "import_pack", "pack_version", version.id,
        detail={"slug": pack.company.slug, "version": pack.version, "keys": sorted(keys)},
    )
    return version


def _v12_images(pack: schema.Pack, bundle) -> list[Problem]:
    """A screen pack's images: present for every variant, a real PNG, and not enormous.

    A pack that names no images is a paper pack and is left alone — paper mode is the first thing
    the PRD cuts, and it must keep working on its own.
    """
    problems: list[Problem] = []
    for index, document in enumerate(pack.documents):
        for code, variant in (document.variants or {}).items():
            path = getattr(variant, "image", None)
            where = f"documents[{index}].variants.{code}"
            if not path:
                continue
            data = bundle.images.get(path)
            if data is None:
                problems.append(
                    Problem(where, "V12",
                            f"{document.ref}: the archive has no {path}.")
                )
                continue
            if not data.startswith(PNG_SIGNATURE):
                problems.append(
                    Problem(where, "V12", f"{document.ref}: {path} is not a PNG.")
                )
            if len(data) > MAX_IMAGE_BYTES:
                problems.append(
                    Problem(where, "V12",
                            f"{document.ref}: {path} is "
                            f"{len(data) // 1024} KB; the limit is "
                            f"{MAX_IMAGE_BYTES // 1024} KB.")
                )
            if not (variant.alt or "").strip():
                problems.append(
                    Problem(where, "V12",
                            f"{document.ref}: an image needs alt text (S2.8).")
                )
    return problems


def _store_images(session: Session, version: PackVersion, pack: schema.Pack, bundle) -> None:
    import hashlib

    wanted = {
        variant.image
        for document in pack.documents
        for variant in (document.variants or {}).values()
        if getattr(variant, "image", None)
    }
    for path in sorted(wanted):
        data = bundle.images[path]
        session.add(
            PackAsset(
                pack_version_id=version.id,
                path=path,
                sha256=hashlib.sha256(data).hexdigest(),
                content_type="image/png",
                byte_size=len(data),
                data=data,
            )
        )
    session.flush()


def _v14_catalogue(session: Session, pack: schema.Pack, sha256: str) -> list[Problem]:
    problems: list[Problem] = []

    seen = session.scalars(
        select(PackVersion.id).where(PackVersion.source_sha256 == sha256)
    ).first()
    if seen is not None:
        problems.append(
            Problem("archive", "V14", "That archive has already been uploaded.")
        )

    content_pack = session.scalars(
        select(ContentPack).where(ContentPack.slug == pack.company.slug)
    ).one_or_none()
    if content_pack is not None:
        highest = session.execute(
            select(func.max(PackVersion.version)).where(
                PackVersion.content_pack_id == content_pack.id
            )
        ).scalar_one()
        if highest is not None and pack.version <= highest:
            problems.append(
                Problem(
                    "version", "V14",
                    f"{pack.company.name} is already in the catalogue at version {highest}; "
                    f"this archive says version {pack.version}. A correction is a new version.",
                )
            )
    return problems


def _from_pydantic(path: str, invalid: ValidationError) -> list[Problem]:
    return [
        Problem(
            path=f"{path}:" + ".".join(str(part) for part in error["loc"]),
            rule="V1",
            message=error["msg"],
        )
        for error in invalid.errors()
    ]
