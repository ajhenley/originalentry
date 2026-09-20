"""The CLI wiring. `packs validate` runs the full ruleset without touching the database, so it is
tested here directly through the Flask CLI runner on a generated pack."""

import pytest
from originalentry.generator import build, write_zip

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


# ── Break-glass sign-in (T13.2) ─────────────────────────────────────────────────────────
#
# `auth issue-link` is the path used when email is down: someone locked out, at the worst
# possible moment, reading a terminal. Every other command here turns a refusal into one plain
# sentence; this one used to let the rate limiter's exception escape as a traceback, which is the
# least helpful thing to meet in an emergency.

def _staff(runner, email):
    """Through the CLI, so the account lands in the session the CLI itself uses."""
    made = runner.invoke(args=["staff", "add", email, "--role", "instructor"])
    assert made.exit_code == 0, made.output
    return email


def test_issue_link_prints_a_link_and_a_code(app, session):
    runner = app.test_cli_runner()
    email = _staff(runner, "brk-ok@example.edu")

    result = runner.invoke(args=["auth", "issue-link", email])

    assert result.exit_code == 0, result.output
    assert "/auth/verify/" in result.output
    assert "Code:" in result.output


def test_issue_link_for_an_unknown_address_says_so_plainly(app, session):
    result = app.test_cli_runner().invoke(args=["auth", "issue-link", "nobody@example.edu"])

    assert result.exit_code != 0
    assert "No account" in result.output
    assert "Traceback" not in result.output


def test_issue_link_explains_the_rate_limit_instead_of_crashing(app, session):
    """The limit is right; meeting it as a stack trace is not."""
    runner = app.test_cli_runner()
    email = _staff(runner, "brk-limit@example.edu")
    for _ in range(6):
        result = runner.invoke(args=["auth", "issue-link", email])

    assert "Traceback" not in result.output
    assert result.exit_code != 0
    assert "Wait a few minutes" in result.output
