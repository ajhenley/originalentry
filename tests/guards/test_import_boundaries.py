"""Module-boundary guard (T3.1): the pure engine must not import Flask, SQLAlchemy, the ORM
models, or grading. ``ledger/snapshot.py`` is the sole allowed door to the database and is
exempt (it is added with the ORM in phase 1)."""

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2] / "originalentry"
LEDGER = ROOT / "ledger"
#: Tagging must not be able to move a score. The concept vocabulary and the mastery report read
#: the marks grading produces; nothing on the grading side may read them back, or a tag would
#: become an input to a grade. Enforced here rather than by a test that grades, tags and regrades
#: and asserts the marks are identical -- that test cannot fail, because tags live in a table the
#: engine never queries. A guard that can fail beats a demonstration that cannot.
TAGGING_MODULES = {"originalentry.models.concepts", "originalentry.services.mastery"}
FORBIDDEN_TOP = {"flask", "sqlalchemy", "psycopg"}
FORBIDDEN_INTERNAL = {"originalentry.models", "originalentry.grading"}
EXEMPT = {"snapshot.py"}


def _imported_modules(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            mods.add(node.module)
    return mods


def test_ledger_stays_pure():
    offenders: list[str] = []
    for path in LEDGER.glob("*.py"):
        if path.name in EXEMPT:
            continue
        for mod in _imported_modules(path):
            top = mod.split(".")[0]
            if top in FORBIDDEN_TOP or mod in FORBIDDEN_INTERNAL:
                offenders.append(f"{path.name} imports {mod}")
    assert not offenders, (
        "ledger/ must import only stdlib + originalentry.money: " + "; ".join(offenders)
    )


def test_grading_never_imports_the_tagging_side():
    offenders: list[str] = []
    paths = list((ROOT / "grading").rglob("*.py")) + [ROOT / "services" / "grades.py"]
    for path in paths:
        for mod in _imported_modules(path):
            if mod in TAGGING_MODULES:
                offenders.append(f"{path.relative_to(ROOT)} imports {mod}")
    assert not offenders, (
        "a concept tag must never be an input to a grade: " + "; ".join(offenders)
    )
