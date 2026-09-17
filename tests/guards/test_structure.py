"""Structural guards (T3.3, T11, T17.3):

- every ``/w/`` route is decorated with ``workspace_view``;
- no template uses an inline ``style`` attribute or an inline event handler (the CSP forbids
  them, so they would silently break in the browser).
"""

import pathlib
import re

from parchment.app import create_app

TEMPLATES = pathlib.Path(__file__).resolve().parents[2] / "parchment" / "templates"

_INLINE_STYLE = re.compile(r"""\bstyle\s*=\s*['"]""")
_INLINE_HANDLER = re.compile(r"""\son[a-z]+\s*=\s*['"]""", re.IGNORECASE)


def test_every_workspace_route_uses_the_decorator():
    app = create_app()
    offenders = []
    for rule in app.url_map.iter_rules():
        if not rule.rule.startswith("/w/"):
            continue
        view = app.view_functions.get(rule.endpoint)
        if not getattr(view, "_is_workspace_view", False):
            offenders.append(rule.endpoint)
    assert not offenders, f"/w/ routes missing @workspace_view: {offenders}"


def test_no_inline_styles_or_handlers_in_templates():
    offenders = []
    for path in TEMPLATES.rglob("*.html"):
        text = path.read_text()
        if _INLINE_STYLE.search(text):
            offenders.append(f"{path.name}: inline style attribute")
        if _INLINE_HANDLER.search(text):
            offenders.append(f"{path.name}: inline event handler")
    assert not offenders, "CSP forbids inline style/handlers: " + "; ".join(offenders)
