"""A21: no account number is written into application code.

An account number means nothing without its pack — two companies both have a 101 — so engine code
finds the accounts it needs by **role**, declared in the pack, and never by number. The PRD asks
for this as a lint rule rather than a review note, because a review will miss it: a literal "101"
reads as harmless anywhere it appears.

The scan is deliberately narrow, so it fails on the thing it is about and not on every integer:
a comparison against an account number, a lookup by one, or an account number written into a
dictionary of them.
"""

import ast
import pathlib
import re

APP = pathlib.Path(__file__).resolve().parents[2] / "parchment"
TEMPLATES = APP / "templates"

# Names that hold an account number, in whatever spelling the code uses for them.
NUMBER_NAMES = {"number", "account_number", "account_no", "acct_number"}
LOOKUP_SUFFIXES = ("_by_number", "_for_number", "by_account_number")

# What an account number looks like in this app's packs: three or four digits, optionally with a
# suffix ("101", "112-1"). A bare 0/1/2 is an index or a count, not a chart.
ACCOUNT_LITERAL = re.compile(r"^\d{3,4}(-\d+)?$")


def _is_account_literal(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str):
            return bool(ACCOUNT_LITERAL.match(node.value))
        if isinstance(node.value, int) and not isinstance(node.value, bool):
            return 100 <= node.value <= 9999
    return False


def _holds_a_number(node: ast.AST) -> bool:
    if isinstance(node, ast.Attribute):
        return node.attr in NUMBER_NAMES
    if isinstance(node, ast.Name):
        return node.id in NUMBER_NAMES
    if isinstance(node, ast.Subscript):
        return _holds_a_number(node.value)
    return False


def _offences(path: pathlib.Path) -> list[str]:
    tree = ast.parse(path.read_text())
    found: list[str] = []

    for node in ast.walk(tree):
        # `account.number == "101"`, and `"101" == account.number`
        if isinstance(node, ast.Compare):
            sides = [node.left, *node.comparators]
            names_one = any(_holds_a_number(side) for side in sides)
            against_a_literal = any(_is_account_literal(side) for side in sides)
            if names_one and against_a_literal:
                found.append(f"{path.name}:{node.lineno}: an account number compared in code")

        # `chart.account_by_number("101")`
        if isinstance(node, ast.Call):
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", "")
            if name.endswith(LOOKUP_SUFFIXES) and any(_is_account_literal(a) for a in node.args):
                found.append(f"{path.name}:{node.lineno}: an account looked up by a literal number")

        # `{"101": ..., "112": ...}` — a chart of accounts smuggled into code. Only string keys
        # count: a pack writes account numbers as text ("112-1" is one), while a dictionary keyed
        # by integers in the same range is something else entirely, usually HTTP status codes.
        if isinstance(node, ast.Dict):
            keys = [k for k in node.keys if k is not None]
            string_keys = [
                k for k in keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)
            ]
            if len(keys) >= 2 and len(string_keys) == len(keys) and all(
                _is_account_literal(k) for k in keys
            ):
                found.append(f"{path.name}:{node.lineno}: account numbers used as dictionary keys")

    return found


def test_no_account_number_literal_in_application_code():
    offences: list[str] = []
    for path in sorted(APP.rglob("*.py")):
        offences.extend(_offences(path))

    assert not offences, (
        "Account numbers belong to a pack, not to the code. Find the account by its role "
        "instead:\n  " + "\n  ".join(offences)
    )


def test_no_account_number_literal_in_a_template():
    """The same rule, in Jinja: a template that names 101 belongs to one company only."""
    pattern = re.compile(r"""(number|account_number)\s*==\s*['"]?\d{3,4}""")
    offences = [
        f"{path.relative_to(TEMPLATES)}:{i}"
        for path in sorted(TEMPLATES.rglob("*.html"))
        for i, line in enumerate(path.read_text().splitlines(), start=1)
        if pattern.search(line)
    ]

    assert not offences, "account numbers compared in a template: " + "; ".join(offences)


def test_the_scan_would_catch_a_real_one(tmp_path):
    """A guard that cannot fail is not a guard, so this pins what it looks for."""
    sample = tmp_path / "offender.py"
    sample.write_text(
        "def cash(chart):\n"
        "    if chart.account.number == '101':\n"
        "        return chart.account_by_number('112')\n"
        "    return {'101': 0, '112': 0}\n"
    )

    assert len(_offences(sample)) == 3


def test_the_scan_leaves_ordinary_numbers_alone(tmp_path):
    sample = tmp_path / "innocent.py"
    sample.write_text(
        "LIMIT = 200\n"
        "PAGES = {400: 'bad request', 404: 'not here', 500: 'trouble'}\n"
        "def page(rows, number):\n"
        "    if number == 2:\n"
        "        return rows[:100]\n"
        "    return {'a': 1, 'b': 2}\n"
    )

    assert _offences(sample) == []
