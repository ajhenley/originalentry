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
from html.parser import HTMLParser

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


# A different colour per version, so the bytes say which version's document was served. Before
# this the fixture had one variant, so the route could have ignored the student's variant
# altogether — or taken it from the URL — and the whole suite would still have passed.
COLOURS = {"A": (0xFF, 0x00, 0x00), "B": (0x00, 0x00, 0xFF)}


def _png(width: int = 4, height: int = 4, colour: tuple[int, int, int] = (255, 255, 255)) -> bytes:
    """A real, tiny PNG — the validator checks the bytes, not the file name."""

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + kind + payload
                + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + bytes(colour) * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _variant_png(code: str) -> bytes:
    return _png(colour=COLOURS[code])


# The shape the artefact reader really produces: most printed lines carry no label of their own,
# so they arrive as ["", value]. 210 of the clinic's 246 rows are like this. A labelled row sits
# between two runs of them so the page has to keep the document's own order.
TEXT_ALTERNATIVE = {
    "fields": [
        ["", "TESTCO ALPHA"],
        ["", "18 Larkspur Lane, Kettle Springs"],
        ["Customer", "Firstborn Supply"],
        ["", "CUSTOMER COPY"],
    ],
    "lines": [["1", "Kayak rack", "1,200.00", "1,200.00"]],
}


def _screen_pack() -> dict:
    """The paper fixture with an image, alt text and a text alternative per variant.

    Two versions, because one cannot show that a student is served their *own* version's
    document. That is the pack's anti-copying mechanism: three versions exist so that copying is
    visible, and a student who could fetch another version's photographs would have the figures
    their own checkpoints are not asking for.
    """
    pack = json.loads(json.dumps(testco_alpha.PACK))
    # What the artefact is, as a manifest-built pack records it — deliberately not the same as
    # `type`, so the Type column cannot pass by reading the wrong field.
    for document in pack["documents"]:
        document["kind"] = "void_cheque"
    pack["variants"] = [{"code": code, "label": f"Variant {code}", "drivers": {}}
                        for code in sorted(COLOURS)]
    base = pack["opening_balances"]["A"]
    pack["opening_balances"] = {code: json.loads(json.dumps(base)) for code in sorted(COLOURS)}
    for document in pack["documents"]:
        document["variants"] = {
            code: {
                "image": f"documents/{code}/{document['ref']}.png",
                "alt": f"{document['display_ref']} to a customer",
                "text_alternative": json.loads(json.dumps(TEXT_ALTERNATIVE)),
            }
            for code in sorted(COLOURS)
        }
    return pack


def _zip(pack=None, images=None, keys=None) -> io.BytesIO:
    pack = pack or _screen_pack()
    if images is None:
        images = {
            variant["image"]: _variant_png(code)
            for document in pack["documents"]
            for code, variant in document.get("variants", {}).items()
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


def _workspace_on(session, client, pack_version, mode="screen", email="reader@example.edu",
                  code="A"):
    variant_id = session.scalars(
        select(Variant.id).where(Variant.pack_version_id == pack_version.id,
                                 Variant.code == code)
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
    assert {asset.path for asset in assets} == {
        "documents/A/INV-1.png", "documents/A/INV-2.png",
        "documents/B/INV-1.png", "documents/B/INV-2.png",
    }
    assert all(asset.content_type == "image/png" for asset in assets)
    assert all(asset.byte_size > 0 for asset in assets)


def test_a_pack_whose_image_is_missing_from_the_archive_is_refused(session, instructor):
    with pytest.raises(PackImportRefused) as refused:
        import_pack_zip(session, _zip(images={}), actor=instructor)

    assert any(problem.rule == "V12" for problem in refused.value.problems)
    assert any("INV-1" in problem.message for problem in refused.value.problems)


def test_a_file_that_is_not_a_png_is_refused(session, instructor):
    images = {path: _variant_png(path.split("/")[1]) for path in (
        "documents/A/INV-1.png", "documents/A/INV-2.png",
        "documents/B/INV-1.png", "documents/B/INV-2.png")}
    images["documents/A/INV-1.png"] = b"not a png at all"

    with pytest.raises(PackImportRefused) as refused:
        import_pack_zip(session, _zip(images=images), actor=instructor)

    assert any(problem.rule == "V12" and "PNG" in problem.message
               for problem in refused.value.problems)


def test_an_image_larger_than_the_limit_is_refused(session, instructor):
    from originalentry.packs.importing import MAX_IMAGE_BYTES

    images = {path: _variant_png(path.split("/")[1]) for path in (
        "documents/A/INV-1.png", "documents/A/INV-2.png",
        "documents/B/INV-1.png", "documents/B/INV-2.png")}
    images["documents/A/INV-1.png"] += b"\x00" * (MAX_IMAGE_BYTES + 1)

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


def test_a_student_is_served_their_own_version_s_document_and_not_another_s(
        session, client, instructor):
    """The pack's anti-copying mechanism, at the serving layer.

    Three versions exist so that copying is visible: the figures printed on the artefact are the
    whole difference between them. The route resolves the asset path through the workspace's own
    _variant_code() and never through anything in the URL — but the module had one variant in its
    fixture and _workspace_on hard-coded "A", so no test ever observed a second version and
    .get("A", {}), or taking the code from a query parameter, would have passed the whole suite.
    """
    version = import_pack_zip(session, _zip(), actor=instructor)
    workspace, _ = _workspace_on(session, client, version, email="onb@example.edu", code="B")

    response = client.get(f"/w/{workspace.public_id}/testco-alpha/documents/INV-1/image")

    assert response.status_code == 200
    assert response.data == _variant_png("B"), "a version-B student was not served B's document"
    assert response.data != _variant_png("A"), "a version-B student was served version A's"


def test_the_page_points_at_the_image_route_not_at_a_variant_path(session, client, instructor):
    """A version is never named in anything a student can edit. The <img> src carries the
    document ref and the workspace, and the variant is resolved server-side from the workspace,
    so there is no path for a student to change to another version's photograph."""
    version = import_pack_zip(session, _zip(), actor=instructor)
    workspace, _ = _workspace_on(session, client, version, email="nopath@example.edu", code="B")

    body = client.get(
        f"/w/{workspace.public_id}/testco-alpha/documents/INV-1"
    ).get_data(as_text=True)

    assert "/documents/INV-1/image" in body
    assert "documents/A/INV-1.png" not in body
    assert "documents/B/INV-1.png" not in body


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


class _Disclosures(HTMLParser):
    """Every <details data-pack-content> on the page, as attribute dicts."""

    def __init__(self):
        super().__init__()
        self.found: list[dict] = []

    def handle_starttag(self, tag, attrs):
        if tag == "details" and any(name == "data-pack-content" for name, _ in attrs):
            self.found.append(dict(attrs))


def _text_disclosure(body):
    """The attributes of the disclosure holding the document's text, not the account menu.

    Every workspace page carries an unrelated <details>, so an unscoped check passes even with
    this one deleted — which is how this test came to assert nothing. Scoping it by
    data-pack-content was right; doing it with `<details([^>]*)data-pack-content` was not,
    because that captures only what *precedes* the attribute, so moving `open` after it gave a
    false failure and a class containing the substring "open" would have too. The whole tag is
    parsed and the attributes are looked up by name, so neither their order nor any other
    attribute's value can reach the assertion.
    """
    parser = _Disclosures()
    parser.feed(body)
    assert parser.found, "the document's text is not inside a disclosure at all"
    return parser.found[0]


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


EMPTY_TERM = re.compile(r"<dt[^>]*>\s*</dt>", re.I)


def test_a_line_with_no_label_is_not_an_empty_definition_term(session, client, instructor):
    """The text alternative is read off the printed artefact's own html, and most printed lines
    carry no label — 210 of the clinic's 246 rows, with D07 and all five of N02-N09 at 100%. Every
    row went through <dt>{{ row[0] }}</dt>, so 85% of the disclosure was empty terms. A definition
    list whose terms are nearly all empty is worse for a screen reader than a plain run of lines,
    and this disclosure is the one surface that has to carry the whole document for a reader who
    cannot use the picture.
    """
    version = import_pack_zip(session, _zip(), actor=instructor)
    workspace, _ = _workspace_on(session, client, version, email="labels@example.edu")

    body = client.get(
        f"/w/{workspace.public_id}/testco-alpha/documents/INV-1"
    ).get_data(as_text=True)

    assert not EMPTY_TERM.search(body), "a label-less line reached the page as an empty <dt>"
    # Each bare line is still there, as a line.
    for line in ("TESTCO ALPHA", "18 Larkspur Lane, Kettle Springs", "CUSTOMER COPY"):
        assert f"<li>{line}</li>" in body, line


def test_a_row_that_really_has_a_label_is_still_a_definition_row(session, client, instructor):
    """The <dl> is not thrown away: a genuine label and value still read as a pair, and the
    document's own order is kept — the two lines above "Customer" are above it on the page and
    "CUSTOMER COPY" is below, because those are the document's lines in sequence."""
    version = import_pack_zip(session, _zip(), actor=instructor)
    workspace, _ = _workspace_on(session, client, version, email="pairs@example.edu")

    body = client.get(
        f"/w/{workspace.public_id}/testco-alpha/documents/INV-1"
    ).get_data(as_text=True)

    assert "<dt class=\"font-medium\">Customer</dt><dd>Firstborn Supply</dd>" in body
    assert body.index("TESTCO ALPHA") < body.index("Firstborn Supply") < body.index("CUSTOMER COPY")


def test_a_document_is_typed_as_what_it_is_in_the_list(session, client, instructor):
    """`kind` was written into the pack and read by nothing but tests, while the list's Type
    column printed the constant "source document" for all 26 rows — the one column where what
    the artefact *is* would earn its place. A void cheque, a time card and a petty cash voucher
    are the judgements this branch added, and the list was the place a student met them.

    The fixture's `type` is sales_invoice and its `kind` is void_cheque, so the column cannot
    pass by reading the wrong field. Presentational only: the schema is unchanged and a pack with
    no kind (Riverbend, which has no printed envelope) still falls back to `type`.
    """
    version = import_pack_zip(session, _zip(), actor=instructor)
    workspace, _ = _workspace_on(session, client, version, email="kinds@example.edu")

    body = client.get(f"/w/{workspace.public_id}/testco-alpha/documents").get_data(as_text=True)

    assert "void cheque" in body
    assert "sales invoice" not in body


def test_a_pack_with_no_kind_still_says_what_its_documents_are(session, client, instructor):
    """Riverbend is live and keeps building one document per transaction, so its documents carry
    no kind at all. The column must not go blank for them."""
    pack = _screen_pack()
    for document in pack["documents"]:
        del document["kind"]
    version = import_pack_zip(session, _zip(pack=pack), actor=instructor)
    workspace, _ = _workspace_on(session, client, version, email="nokind@example.edu")

    body = client.get(f"/w/{workspace.public_id}/testco-alpha/documents").get_data(as_text=True)

    assert "sales invoice" in body


def test_the_document_page_says_the_same_thing_the_list_did(session, client, instructor):
    """The list's Type column was taught to print `kind`; the document's own page still printed
    `doc_type`. So the same artefact was a "void cheque" in the list and a "source document" one
    click later, and the two surfaces disagreed about what the student was holding — a
    disagreement that did not exist before the column was fixed.

    The fixture's `type` is sales_invoice and its `kind` is void_cheque, so this cannot pass by
    reading the wrong field.
    """
    version = import_pack_zip(session, _zip(), actor=instructor)
    workspace, _ = _workspace_on(session, client, version, email="samekind@example.edu")

    body = client.get(
        f"/w/{workspace.public_id}/testco-alpha/documents/INV-1"
    ).get_data(as_text=True)

    assert "void cheque" in body
    assert "source document" not in body


def test_a_document_page_with_no_kind_still_says_what_it_is(session, client, instructor):
    """The fallback matters on the page as much as in the list: Riverbend's documents carry no
    kind and must not head their page with a blank."""
    pack = _screen_pack()
    for document in pack["documents"]:
        del document["kind"]
    version = import_pack_zip(session, _zip(pack=pack), actor=instructor)
    workspace, _ = _workspace_on(session, client, version, email="nokindpage@example.edu")

    body = client.get(
        f"/w/{workspace.public_id}/testco-alpha/documents/INV-1"
    ).get_data(as_text=True)

    assert "sales invoice" in body
