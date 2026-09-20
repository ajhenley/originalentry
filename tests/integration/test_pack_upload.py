"""Uploading a pack (I1.7, T5.5, V14).

A pack is validated before it becomes available, and a version is immutable once used: the same
archive cannot arrive twice, and a correction has to be a new version rather than an edit.
"""

import copy
import io
import json
import zipfile

import pytest
from originalentry.models import ContentPack, PackVersion, User
from originalentry.packs.importing import PackImportRefused, import_pack_zip
from sqlalchemy import func, select

from tests.packs import testco_alpha

pytestmark = pytest.mark.db


def _zip(pack=None, keys=None):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("pack.json", json.dumps(pack or testco_alpha.PACK))
        for code, key in (keys or {"A": testco_alpha.KEY_A}).items():
            archive.writestr(f"answer_keys/{code}.json", json.dumps(key))
    buffer.seek(0)
    return buffer


@pytest.fixture
def instructor(session):
    user = User(email="uploader@example.edu", role="instructor")
    session.add(user)
    session.flush()
    return user


def test_a_good_pack_lands_in_the_catalogue(session, instructor):
    version = import_pack_zip(session, _zip(), actor=instructor)

    assert version.version == 1
    assert version.source_sha256
    pack = session.get(ContentPack, version.content_pack_id)
    assert pack.company_name == "TestCo Alpha"
    assert session.execute(
        select(func.count()).select_from(PackVersion).where(
            PackVersion.content_pack_id == pack.id
        )
    ).scalar_one() == 1


def test_the_same_archive_twice_is_refused(session, instructor):
    import_pack_zip(session, _zip(), actor=instructor)

    with pytest.raises(PackImportRefused) as refused:
        import_pack_zip(session, _zip(), actor=instructor)

    assert any("already" in problem.message for problem in refused.value.problems)


def test_a_version_that_is_not_newer_is_refused(session, instructor):
    newer = copy.deepcopy(testco_alpha.PACK)
    newer["version"] = 3
    import_pack_zip(session, _zip(newer), actor=instructor)

    older = copy.deepcopy(testco_alpha.PACK)
    older["version"] = 2
    older["company"]["name"] = "TestCo Alpha (fixed)"  # different bytes, same slug
    with pytest.raises(PackImportRefused) as refused:
        import_pack_zip(session, _zip(older), actor=instructor)

    assert any(problem.rule == "V14" for problem in refused.value.problems)


def test_a_newer_version_sits_beside_the_old_one(session, instructor):
    first = import_pack_zip(session, _zip(), actor=instructor)
    second_pack = copy.deepcopy(testco_alpha.PACK)
    second_pack["version"] = 2

    second = import_pack_zip(session, _zip(second_pack), actor=instructor)

    assert second.content_pack_id == first.content_pack_id
    assert {v.version for v in session.scalars(
        select(PackVersion).where(PackVersion.content_pack_id == first.content_pack_id)
    )} == {1, 2}


def test_a_pack_that_fails_a_rule_is_refused_with_every_problem_named(session, instructor):
    broken = copy.deepcopy(testco_alpha.PACK)
    for account in broken["accounts"]:
        if "retained_earnings" in account.get("roles", []):
            account["roles"] = []

    with pytest.raises(PackImportRefused) as refused:
        import_pack_zip(session, _zip(broken), actor=instructor)

    assert any(problem.rule == "V5" for problem in refused.value.problems)
    # Nothing was written for *this* pack. The count is scoped rather than global, because the
    # database a developer runs against may hold other companies already.
    assert session.scalars(
        select(ContentPack).where(ContentPack.slug == broken["company"]["slug"])
    ).one_or_none() is None


def test_a_pack_whose_key_does_not_replay_is_refused(session, instructor):
    key = copy.deepcopy(testco_alpha.KEY_A)
    key["expected_balances"]["adjusted"]["101"] = 999999

    with pytest.raises(PackImportRefused) as refused:
        import_pack_zip(session, _zip(keys={"A": key}), actor=instructor)

    assert any(problem.rule == "V9" for problem in refused.value.problems)


# ── W1 reaches the author (T5.4) ────────────────────────────────────────────────────────

def _pack_saying_correct(slug: str) -> dict:
    pack = copy.deepcopy(testco_alpha.PACK)
    pack["company"]["slug"] = slug
    pack["documents"][0]["guidance"] = "Choose the correct journal for this document."
    return pack


def test_a_pack_that_says_correct_still_loads(session, instructor):
    """A warning is not a refusal: "a correcting entry" is ordinary accounting prose."""
    version = import_pack_zip(session, _zip(_pack_saying_correct("w1-loads")), actor=instructor)

    assert version.id is not None


def test_the_upload_screen_shows_the_author_what_it_noticed(client, session, instructor):
    session.commit()
    client.sign_in(instructor)

    response = client.post(
        "/staff/catalogue",
        data={"pack": (_zip(_pack_saying_correct("w1-screen")), "pack.zip")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "W1" in body
    assert "in the catalogue" in body       # it loaded, and says so
