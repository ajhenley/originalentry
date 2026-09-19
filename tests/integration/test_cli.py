"""The CLI wiring. `packs validate` runs the full ruleset without touching the database, so it is
tested here directly through the Flask CLI runner on a generated pack."""

import pytest
from parchment.generator import build, write_zip

from tests.packs import testco_alpha_source

pytestmark = pytest.mark.db  # uses the shared app fixture


def test_packs_validate_accepts_a_generated_pack(app, tmp_path):
    data, _ = write_zip(build(testco_alpha_source.SOURCE, render_images=False))
    pack = tmp_path / "pack.zip"
    pack.write_bytes(data)

    result = app.test_cli_runner().invoke(args=["packs", "validate", str(pack)])
    assert result.exit_code == 0, result.output
    assert "Valid" in result.output


def test_packs_validate_reports_a_broken_archive(app, tmp_path):
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"not a zip")
    result = app.test_cli_runner().invoke(args=["packs", "validate", str(bad)])
    assert result.exit_code != 0
