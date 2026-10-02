"""Document images in screen mode (S2.1, S2.8, T11, V12).

An image is the document, so it is served only to the student whose books it belongs to, only in
screen mode, and only for their own variant. Nothing about the image is guessable from a URL: the
route is inside the workspace, and the bytes live in Postgres rather than a public bucket.
"""

import io
import json
import re
import struct
import zipfile
import zlib

import pytest
from originalentry.models import (
    Assignment,
    PackAsset,
    PackVersion,
    Section,
    User,
    Variant,
    Workspace,
)
from originalentry.packs.importing import PackImportRefused, import_pack_zip
from sqlalchemy import select

from tests.packs import testco_alpha

pytestmark = pytest.mark.db


def _png(width: int = 4, height: int = 4) -> bytes:
    """A real, tiny PNG — the validator checks the bytes, not the file name."""

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + kind + payload
                + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\xff\xff\xff" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _screen_pack() -> dict:
    """The paper fixture with an image, alt text and a text alternative per variant."""
    pack = json.loads(json.dumps(testco_alpha.PACK))
    for document in pack["documents"]:
        document["variants"] = {
            "A": {
                "image": f"documents/A/{document['ref']}.png",
                "alt": f"{document['display_ref']} to a customer",
                "text_alternative": {"fields": [["Customer", "Firstborn Supply"]],
                                     "lines": [["1", "Kayak rack", "1,200.00", "1,200.00"]]},
            }
        }
    return pack


def _zip(pack=None, images=None, keys=None) -> io.BytesIO:
    pack = pack or _screen_pack()
    if images is None:
        images = {
            variant["image"]: _png()
            for document in pack["documents"]
            for variant in document.get("variants", {}).values()
            if variant.get("image")
        }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("pack.json", json.dumps(pack))
        for code, key in (keys or {"A": testco_alpha.KEY_A}).items():
            archive.writestr(f"answer_keys/{code}.json", json.dumps(key))
        for path, data in images.items():
            archive.writestr(path, data)
    buffer.seek(0)
    return buffer


@pytest.fixture
def instructor(session):
    user = User(email="images@example.edu", role="instructor")
    session.add(user)
    session.flush()
    return user


def _workspace_on(session, client, pack_version, mode="screen", email="reader@example.edu"):
    variant_id = session.scalars(
        select(Variant.id).where(Variant.pack_version_id == pack_version.id,
                                 Variant.code == "A")
    ).one()
    section = Section(name="Sec", join_code=f"img-{email[:4]}")
    student = User(email=email, given_name="Ivo", family_name="Marin")
    session.add_all([section, student])
    session.flush()
    assignment = Assignment(section_id=section.id, title="December", company_policy="fixed",
                            fixed_pack_version_id=pack_version.id, mode=mode)
    session.add(assignment)
    session.flush()
    workspace = Workspace(assignment_id=assignment.id, student_id=student.id,
                          pack_version_id=pack_version.id, variant_id=variant_id,
                          status="in_progress")
    session.add(workspace)
    session.flush()
    client.sign_in(student)
    return workspace, student


def test_a_screen_pack_brings_its_images_with_it(session, instructor):
    version = import_pack_zip(session, _zip(), actor=instructor)

    assert version.has_images
    assets = session.scalars(
        select(PackAsset).where(PackAsset.pack_version_id == version.id)
    ).all()
    assert {asset.path for asset in assets} == {"documents/A/INV-1.png", "documents/A/INV-2.png"}
    assert all(asset.content_type == "image/png" for asset in assets)
    assert all(asset.byte_size > 0 for asset in assets)


def test_a_pack_whose_image_is_missing_from_the_archive_is_refused(session, instructor):
    with pytest.raises(PackImportRefused) as refused:
        import_pack_zip(session, _zip(images={}), actor=instructor)

    assert any(problem.rule == "V12" for problem in refused.value.problems)
    assert any("INV-1" in problem.message for problem in refused.value.problems)


def test_a_file_that_is_not_a_png_is_refused(session, instructor):
    images = {"documents/A/INV-1.png": b"not a png at all",
              "documents/A/INV-2.png": _png()}

    with pytest.raises(PackImportRefused) as refused:
        import_pack_zip(session, _zip(images=images), actor=instructor)

    assert any(problem.rule == "V12" and "PNG" in problem.message
               for problem in refused.value.problems)


def test_an_image_larger_than_the_limit_is_refused(session, instructor):
    from originalentry.packs.importing import MAX_IMAGE_BYTES

    images = {"documents/A/INV-1.png": _png() + b"\x00" * (MAX_IMAGE_BYTES + 1),
              "documents/A/INV-2.png": _png()}

    with pytest.raises(PackImportRefused) as refused:
        import_pack_zip(session, _zip(images=images), actor=instructor)

    assert any(problem.rule == "V12" for problem in refused.value.problems)


def test_the_student_is_served_their_own_documents_image(session, client, instructor):
    version = import_pack_zip(session, _zip(), actor=instructor)
    workspace, _ = _workspace_on(session, client, version)

    response = client.get(f"/w/{workspace.public_id}/testco-alpha/documents/INV-1/image")

    assert response.status_code == 200
    assert response.headers["Content-Type"] == "image/png"
    assert response.data.startswith(b"\x89PNG")
    assert "private" in response.headers["Cache-Control"]


def test_another_student_cannot_read_that_image(session, client, instructor):
    version = import_pack_zip(session, _zip(), actor=instructor)
    workspace, _ = _workspace_on(session, client, version)
    intruder = User(email="intruder-images@example.edu")
    session.add(intruder)
    session.flush()
    client.sign_in(intruder)

    response = client.get(f"/w/{workspace.public_id}/testco-alpha/documents/INV-1/image")

    assert response.status_code == 404


def test_paper_mode_serves_no_images_at_all(session, client, instructor):
    version = import_pack_zip(session, _zip(), actor=instructor)
    workspace, _ = _workspace_on(session, client, version, mode="paper",
                                 email="paper@example.edu")

    response = client.get(f"/w/{workspace.public_id}/testco-alpha/documents/INV-1/image")

    assert response.status_code == 404
    page = client.get(f"/w/{workspace.public_id}/testco-alpha/documents/INV-1")
    assert "/image" not in page.get_data(as_text=True)


def test_screen_mode_shows_the_image_and_still_offers_the_text(session, client, instructor):
    version = import_pack_zip(session, _zip(), actor=instructor)
    workspace, _ = _workspace_on(session, client, version, email="screen@example.edu")

    body = client.get(
        f"/w/{workspace.public_id}/testco-alpha/documents/INV-1"
    ).get_data(as_text=True)

    assert "/documents/INV-1/image" in body
    assert 'alt="' in body                   # every image carries its alt text (S2.8)
    assert "View as text" in body            # and the reading that does not need the image


DISCLOSURE = re.compile(r"<details([^>]*)data-pack-content", re.I)


def _text_disclosure(body):
    """The disclosure holding the document's text, not the account menu.

    Every workspace page carries an unrelated <details>, so an unscoped check passes even with
    this one deleted — which is how this test came to assert nothing. Matching the attributes of
    the tag that carries data-pack-content also stops the assertion depending on whether `open`
    happens to be written before or after the class.
    """
    found = DISCLOSURE.search(body)
    assert found, "the document's text is not inside a disclosure at all"
    return found.group(1)


def test_the_text_is_behind_a_disclosure_when_there_is_a_picture(session, client, instructor):
    """The document should be the page. The text stays reachable, because an alt attribute
    naming the document tells a screen reader nothing about its figures."""
    version = import_pack_zip(session, _zip(), actor=instructor)
    workspace, _ = _workspace_on(session, client, version, email="disclosure@example.edu")

    body = client.get(
        f"/w/{workspace.public_id}/testco-alpha/documents/INV-1"
    ).get_data(as_text=True)

    assert "open" not in _text_disclosure(body)
    assert "View as text" in body


def test_the_text_is_open_when_there_is_no_picture(session, client, instructor):
    """A pack with no images would otherwise show nothing at all."""
    version = import_pack_zip(session, _zip(), actor=instructor)
    workspace, _ = _workspace_on(session, client, version, mode="paper",
                                 email="disclosure-paper@example.edu")

    body = client.get(
        f"/w/{workspace.public_id}/testco-alpha/documents/INV-1"
    ).get_data(as_text=True)

    assert "open" in _text_disclosure(body)


def test_a_paper_pack_keeps_loading_as_one(session, instructor):
    version = import_pack_zip(session, _zip(pack=testco_alpha.PACK, images={}), actor=instructor)

    assert not version.has_images
    assert session.scalars(
        select(PackAsset).where(PackAsset.pack_version_id == version.id)
    ).first() is None
    assert session.get(PackVersion, version.id).has_images is False
