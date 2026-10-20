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
#: Checked by module suffix and by imported name, because neither alone is enough. The module is
#: matched on its tail so a relative `..services.mastery` and an absolute
#: `originalentry.services.mastery` are the same offence -- resolving relative imports properly
#: would need each file's package path and buys nothing here. The names are matched because
#: Concept and ConceptTag are re-exported from models/__init__, so the module a violation names
#: would be `..models`, which grading/ imports legitimately on almost every line.
TAGGING_SUFFIXES = ("services.mastery", "models.concepts")
TAGGING_NAMES = {"Concept", "ConceptTag"}


def _tagging_offences(path: pathlib.Path) -> list[str]:
    """Every import in this file that would let a concept tag reach a grade."""
    found: list[str] = []
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.endswith(TAGGING_SUFFIXES):
                    found.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = (node.module or "").lstrip(".")
            names = {alias.name for alias in node.names}
            if module.endswith(TAGGING_SUFFIXES):
                found.append(f"{'.' * node.level}{module}")
            for name in sorted(names & TAGGING_NAMES):
                found.append(f"{'.' * node.level}{module}.{name}")
    return found
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
        for offence in _tagging_offences(path):
            offenders.append(f"{path.relative_to(ROOT)} imports {offence}")
    assert not offenders, (
        "a concept tag must never be an input to a grade: " + "; ".join(offenders)
    )


#: Every spelling that would really be used. The first two are the idiom: 34 of the 55 ImportFrom
#: nodes under grading/ and in grades.py are relative, and Concept/ConceptTag are re-exported from
#: models/__init__, so `from ..models import ConceptTag` is the natural way to introduce the
#: violation and the least visible.
OFFENDING_SPELLINGS = (
    "from ..services.mastery import assignment_mastery",
    "from ..models import ConceptTag",
    "from originalentry.services.mastery import assignment_mastery",
    "from originalentry.models import Concept",
    "from ..models.concepts import ConceptTag",
    "import originalentry.services.mastery",
)


def test_the_tagging_scan_would_catch_a_real_one(tmp_path):
    """Guards the guard, which previously could not fail.

    _imported_modules records an ImportFrom only when node.level == 0 -- absolute imports -- so a
    check built on it saw none of the relative imports this codebase actually uses. A green safety
    net over the one anti-goal the spec says is enforced structurally is worse than no net, because
    nobody looks again.
    """
    for source in OFFENDING_SPELLINGS:
        offender = tmp_path / "offender.py"
        offender.write_text(source + "\n")
        assert _tagging_offences(offender), f"the scan did not catch: {source}"


def test_the_tagging_scan_does_not_cry_wolf(tmp_path):
    innocent = tmp_path / "innocent.py"
    innocent.write_text(
        "from ..models import Workspace\n"
        "from ..services.grades import final_marks\n"
        "from .conceptual_helpers import something\n"
    )

    assert _tagging_offences(innocent) == []
