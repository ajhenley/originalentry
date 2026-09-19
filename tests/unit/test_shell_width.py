"""The header, the content and the footer line up on every page.

The console is table-heavy and wants a wider column than a student's workspace, so the width is a
per-layout decision — but it is *one* decision: everything that frames a page carries
``data-shell`` and takes its width from the same block, so a header can never sit wider than the
content under it.
"""

import re

import pytest
from parchment.app import create_app

SHELL = re.compile(r'<(?:main|div|footer|header)[^>]*\bdata-shell\b[^>]*class="([^"]+)"')
CLASS_FIRST = re.compile(r'<(?:main|div|footer|header)[^>]*class="([^"]+)"[^>]*\bdata-shell\b')
WIDTH = re.compile(r"\bmax-w-([a-z0-9]+)\b")


@pytest.fixture(scope="module")
def client():
    return create_app().test_client()


def _shell_widths(html: str) -> list[str]:
    widths = []
    for match in list(SHELL.finditer(html)) + list(CLASS_FIRST.finditer(html)):
        found = WIDTH.search(match.group(1))
        if found:
            widths.append(found.group(1))
    return widths


@pytest.mark.parametrize("path", ["/", "/privacy", "/terms", "/auth/sign-in"])
def test_a_page_frames_itself_at_one_width(client, path):
    html = client.get(path, follow_redirects=True).get_data(as_text=True)

    widths = _shell_widths(html)

    assert len(widths) >= 2, f"{path} has no framing elements marked data-shell"
    assert len(set(widths)) == 1, f"{path} frames itself at {sorted(set(widths))}"


def test_no_frame_hard_codes_its_own_width():
    """The drift this guards against: a console header widened without its footer following.

    A framing element takes its width from ``shell_width``, never from a class written into the
    markup beside it.
    """
    import pathlib

    templates = pathlib.Path(__file__).resolve().parents[2] / "parchment" / "templates"
    offenders = []
    for path in sorted(templates.rglob("*.html")):
        for i, line in enumerate(path.read_text().splitlines(), start=1):
            if "data-shell" in line and "{{ shell_width }}" not in line:
                offenders.append(f"{path.relative_to(templates)}:{i}")

    assert not offenders, (
        "these frames set their own width instead of the layout's: " + "; ".join(offenders)
    )
