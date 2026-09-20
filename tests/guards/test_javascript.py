"""The JavaScript is tested too, and it says nothing the interface may not say.

``save.js`` decides when to retry, when to keep an entry and when to give up, and that decision is
a pure function with its own tests under node's built-in runner. Running them from here means one
command verifies the whole app, and a broken decision fails the same suite as a broken ledger.
"""

import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
JS = ROOT / "originalentry" / "static" / "js"
BANNED = re.compile(r"\b(correct|incorrect|right|wrong)\b", re.IGNORECASE)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed here")
def test_the_javascript_tests_pass():
    # Expand the glob here — subprocess does not run a shell, and node treats an unexpanded
    # pattern as a literal (missing) path.
    test_files = sorted(str(p) for p in (ROOT / "tests" / "js").glob("*.test.js"))
    assert test_files, "no JavaScript tests found under tests/js/"
    result = subprocess.run(
        ["node", "--test", *test_files],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_no_banned_word_in_any_script():
    """A7 reaches the scripts as well: they write to the page the student reads."""
    offenders = []
    for path in JS.glob("*.js"):
        for line_no, line in enumerate(path.read_text().splitlines(), start=1):
            if BANNED.search(line):
                offenders.append(f"{path.name}:{line_no}: {line.strip()}")
    assert not offenders, "banned words in the scripts: " + "; ".join(offenders)
