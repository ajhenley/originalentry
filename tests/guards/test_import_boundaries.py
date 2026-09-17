"""Module-boundary guard (T3.1): the pure engine must not import Flask, SQLAlchemy, the ORM
models, or grading. ``ledger/snapshot.py`` is the sole allowed door to the database and is
exempt (it is added with the ORM in phase 1)."""

import ast
import pathlib

LEDGER = pathlib.Path(__file__).resolve().parents[2] / "parchment" / "ledger"
FORBIDDEN_TOP = {"flask", "sqlalchemy", "psycopg"}
FORBIDDEN_INTERNAL = {"parchment.models", "parchment.grading"}
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
        "ledger/ must import only stdlib + parchment.money: " + "; ".join(offenders)
    )
