"""The generator's output imports cleanly (A15, A19): a zip the generator makes goes through the
same upload path a real pack does — schema, every V-rule including V9 (replay reproduces the
computed balances), images, and V14 — and lands in the catalogue. A second upload is refused.
"""

import copy
import io
import secrets

import pytest
from parchment.generator import build, write_zip
from parchment.models import Account, AnswerKey, PackAsset, PackVersion
from parchment.packs.importing import PackImportRefused, import_pack_zip
from sqlalchemy import func, select

from tests.packs import testco_alpha_source

pytestmark = pytest.mark.db


def test_generated_zip_imports_and_reimport_is_refused(session):
    # A unique slug keeps the test hermetic on the shared dev catalogue (V14 is about what the
    # catalogue already holds); the reimport is still refused on the duplicate checksum.
    source = copy.deepcopy(testco_alpha_source.SOURCE)
    source["company"]["slug"] = f"testco-gen-{secrets.token_hex(4)}"
    data, _ = write_zip(build(source, render_images=True))

    version = import_pack_zip(session, io.BytesIO(data))
    assert isinstance(version, PackVersion)

    # Content landed: the eight accounts, one answer key, two images.
    accounts = session.execute(
        select(func.count()).select_from(Account).where(Account.pack_version_id == version.id)
    ).scalar_one()
    assert accounts == 8
    keys = session.scalars(
        select(AnswerKey).where(AnswerKey.pack_version_id == version.id)
    ).all()
    assert len(keys) == 1
    images = session.execute(
        select(func.count()).select_from(PackAsset).where(PackAsset.pack_version_id == version.id)
    ).scalar_one()
    assert images == 2

    # The very same archive cannot be uploaded twice (V14).
    with pytest.raises(PackImportRefused) as exc:
        import_pack_zip(session, io.BytesIO(data))
    assert any(p.rule == "V14" for p in exc.value.problems)
