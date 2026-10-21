"""One query for an assignment's class-facing workspaces, and the guard that keeps it honest.

A teacher works their own assignment in a private practice copy: an ordinary workspace whose
``staff_practice`` flag is set (``workspaces.is_own_practice`` is the write side of it). The read
side is this: a practice copy must never reach a class-level number, export or GradeRun beside
real students. A teacher's practice attempts sitting in a student gradebook is the failure this
whole design exists to prevent, and it is the one an instructor would have no reason to disbelieve
-- the figures would simply be wrong, quietly, for a term.

Nine cohort reads had to start excluding practice copies. Nine sites each remembering to add
``staff_practice.is_(False)`` is not a design, it is nine chances to forget, and the tenth site
written next year has nobody to remind it. So there is **one** query --
``workspaces.class_workspaces`` -- with ``class_workspace_ids`` for an ``IN`` clause and
``class_workspace_clause`` for a site that needs its own joins and extra columns, and this guard
insists that every class-level question goes through one of the three.

**What counts as a cohort read.** A statement that queries ``Workspace.assignment_id`` and does
*not* also filter ``student_id`` *to a particular person*. A per-person query names the student,
so a practice copy only ever matches its own owner and must NOT be excluded -- excluding it is how
a teacher loses the way back into their own copy.

"To a particular person" is the whole of the distinction, and asking for the words
``student_id`` is not enough to draw it: four of the nine cohort reads say
``Workspace.student_id == User.id`` to *join* the student's name onto the row, which filters
nobody. The first version of this guard matched the text and reported seven of the nine -- the
progress table, the grading roster and the archived-books list, three of the screens a teacher
actually looks at, all passed it clean. So the comparison is read from the syntax tree instead:
``Workspace.student_id == User.id`` compares the column to another model's column and is a join;
``== student.id`` or ``== current_user.id`` names a person and is a filter.

**Why the scan looks for ``Workspace.assignment_id`` in any form and not for
``Workspace.assignment_id ==``.** ``services/purge.py`` writes
``Workspace.assignment_id.in_(assignment_ids or [0])`` and ``staff/views.py`` names the column in
a ``select``/``group_by`` pair with no comparison at all. An ``==``-only pattern would see
neither, so ``test_every_exempt_module_really_queries_workspaces`` would pass vacuously for purge
-- and that test is the only thing keeping the exemption honest.

**One shape the scan deliberately does not treat as a cohort read:**
``staff/views._workspace_or_404`` matches on ``filter_by(public_id=..., assignment_id=...)``. It
is keyed by ``public_id``, so it returns one named workspace rather than a cohort, and it is how a
teacher reaches their own copy from the console. It never becomes an ``ast.Attribute`` on
``Workspace`` either, so the scan does not see it; that is noted here so the omission is a
decision somebody made rather than a hole somebody left.

Source inspection, in the idiom of
``test_scoping.py::test_every_scoped_console_route_goes_through_one_of_the_two_lookups``: what
matters is that the query is *written* through the chokepoint, and no amount of calling the nine
sites proves that about the tenth.
"""

from __future__ import annotations

import ast
import pathlib
from typing import NamedTuple

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2] / "originalentry"

#: Modules that query workspaces by assignment, and must do it through class_workspaces.
WALKERS = ("services/diagnostics.py", "services/mastery.py", "services/progress.py",
           "services/marks_export.py", "services/grades.py", "services/assignments.py",
           "staff/views.py", "student/views.py", "packs/migrate.py", "services/purge.py",
           # Not in the task brief's literal, and found by the completeness test below rather
           # than by anybody's memory: `choose_company` queries (assignment, student), which is
           # a per-person read and so needs no exclusion -- but a module nobody classified is
           # exactly what that test exists to surface.
           "services/multicompany.py")

#: Queries that are not cohort reads, and why. A per-person query filters student_id, so a
#: practice copy only ever matches its owner; the two write paths have their own decisions.
EXEMPT = {
    "services/purge.py": "retention deletion must reach every row or it orphans FK records",
    "packs/migrate.py": "a migration archives practice copies (Task 6), it does not report them",
}

#: The chokepoint, and the only three spellings a cohort read may reach it by. `class_workspaces`
#: and `class_workspace_ids` answer the question outright; `class_workspace_clause` is for a site
#: that needs its own joins or extra columns and composes the chokepoint's filter into its own
#: query. Repeating the practice condition inline is what this guard forbids: that is a tenth
#: definition of the rule, which is how the nine drift apart.
CHOKEPOINT = "originalentry/workspaces.py"
CHOKEPOINT_CALLS = ("class_workspaces(", "class_workspace_ids(", "class_workspace_clause(")
CHOKEPOINT_NAMES = ("class_workspaces", "class_workspace_ids", "class_workspace_clause")


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}


def _is_workspace_column(node: ast.AST, column: str) -> bool:
    return (isinstance(node, ast.Attribute) and node.attr == column
            and isinstance(node.value, ast.Name) and node.value.id == "Workspace")


def _is_model_column(node: ast.AST) -> bool:
    """``User.id``, ``Assignment.id`` -- another mapped column, so a comparison to it is a join.

    Judged by the capital letter, which is what tells a model class from an instance in this
    codebase's own idiom: ``User.id`` is a column and ``student.id``, ``current_user.id``,
    ``assignment.id`` are values. A join condition filters nobody; a value does.
    """
    return (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
            and node.value.id[:1].isupper())


def _filter_by_keywords(node: ast.AST) -> dict[str, ast.AST]:
    """The keywords of a ``filter_by(...)`` call, by name.

    ``filter_by`` is the one query idiom in this codebase that names a column **without ever
    mentioning the model**, so it is invisible to every check built on attribute access -- and it
    is already written here twice (``staff/views.py:245``, ``decorators.py:126``), which makes it
    the next person's natural spelling rather than a hypothetical one. Scoped to ``filter_by``
    deliberately: a bare search for an ``assignment_id=`` keyword would report
    ``Workspace(assignment_id=..., student_id=...)``, ``AssignmentChoice(assignment_id=...)`` and
    six other constructors, none of which is a query.
    """
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "filter_by"):
        return {kw.arg: kw.value for kw in node.keywords if kw.arg}
    return {}


def _queries_an_assignment(node: ast.AST) -> bool:
    """Either spelling of "by assignment": ``Workspace.assignment_id`` or
    ``filter_by(assignment_id=...)``."""
    return (_is_workspace_column(node, "assignment_id")
            or "assignment_id" in _filter_by_keywords(node))


def _names_a_student(statement: ast.AST) -> bool:
    """Whether this statement filters ``Workspace.student_id`` down to a particular person."""
    for node in ast.walk(statement):
        if isinstance(node, ast.Compare) and _is_workspace_column(node.left, "student_id"):
            if any(not _is_model_column(other) for other in node.comparators):
                return True
        # ``Workspace.student_id.in_(ids)`` -- a named set of people, not a cohort.
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "in_"
                and _is_workspace_column(node.func.value, "student_id")):
            return True
        student = _filter_by_keywords(node).get("student_id")
        if student is not None and not _is_model_column(student):
            return True
    return False


def _names_one_workspace(statement: ast.AST) -> bool:
    """Whether this statement is keyed by a workspace's own ``public_id``.

    ``staff/views._workspace_or_404`` is written ``filter_by(public_id=..., assignment_id=...)``:
    it returns the one workspace a teacher clicked on, which is how they reach their own practice
    copy from the console, and a question about one named row cannot be a question about a class.
    It was always meant to be outside this guard's business -- the docstring above has said so
    since the first version -- but until ``filter_by`` became visible, saying it in prose was
    enough. Now the scan can see the query, so the exemption has to be in the code.
    """
    for node in ast.walk(statement):
        if "public_id" in _filter_by_keywords(node):
            return True
        if isinstance(node, ast.Compare) and _is_workspace_column(node.left, "public_id"):
            return True
    return False


def _practice_conditions(path: pathlib.Path) -> bool:
    """Whether this file writes the practice condition into a query itself, in either spelling.

    ``Workspace.staff_practice`` or ``filter_by(staff_practice=...)``. Read off the syntax tree
    rather than by regex, so that **constructing** a practice copy --
    ``Workspace(..., staff_practice=True)``, which Task 6 has to do -- is not mistaken for a
    second copy of the rule. Matching the text ``staff_practice =`` cannot tell those apart.
    """
    tree = ast.parse(path.read_text(), filename=str(path))
    return any(_is_workspace_column(node, "staff_practice")
               or "staff_practice" in _filter_by_keywords(node)
               for node in ast.walk(tree))


class Query(NamedTuple):
    """One statement that queries ``Workspace.assignment_id``, and where to find it."""

    line: int
    source: str
    statement: ast.stmt

    def __str__(self) -> str:
        return f"{self.line}  {self.source.splitlines()[0].strip()}"


def _assignment_queries(path: pathlib.Path) -> list[Query]:
    """Every statement in this file that queries ``Workspace.assignment_id``.

    One record per enclosing *statement*: the statement is the unit a query is written in --
    ``session.scalars(select(Workspace).where(...))`` is one statement across six lines -- and it
    is the unit in which the ``student_id`` filter sits beside the ``assignment_id`` one. Judging
    a single line instead would read ``Workspace.assignment_id == assignment.id,`` as a cohort
    read in every per-person query in the codebase.
    """
    text = path.read_text()
    tree = ast.parse(text, filename=str(path))
    parents = _parents(tree)
    found: dict[int, Query] = {}
    for node in ast.walk(tree):
        if not _queries_an_assignment(node):
            continue
        statement: ast.AST | None = node
        while statement is not None and not isinstance(statement, ast.stmt):
            statement = parents.get(statement)
        if statement is None:  # pragma: no cover - a module body is always made of statements
            continue
        found[statement.lineno] = Query(
            statement.lineno, ast.get_source_segment(text, statement) or "", statement)
    return [found[line] for line in sorted(found)]


def _asks_about_a_cohort(path: pathlib.Path) -> bool:
    """Whether this file asks a question about an assignment's workspaces *in any way*.

    Naming the column is one way; calling the chokepoint is the other, and a module that has been
    routed through it stops mentioning ``Workspace.assignment_id`` altogether -- five of the nine
    did exactly that. Without the second half, every site fixed would quietly drop out of the
    walker list and the list would decay into whichever sites are still broken.
    """
    return bool(_assignment_queries(path)) or any(
        call in path.read_text() for call in CHOKEPOINT_CALLS)


def _cohort_reads(path: pathlib.Path) -> list[Query]:
    """The subset that asks a class-level question: nothing in it names a particular student."""
    return [q for q in _assignment_queries(path)
            if not _names_a_student(q.statement) and not _names_one_workspace(q.statement)]


def _offenders(path: pathlib.Path) -> list[Query]:
    """Cohort reads in this file that do not go through the chokepoint."""
    return [q for q in _cohort_reads(path)
            if not any(call in q.source for call in CHOKEPOINT_CALLS)]


def test_every_walker_is_a_real_file():
    """A walker naming no file guards nothing, and an exempt name matching no file excuses
    nothing. Rename a module and this fails, rather than the lists quietly ceasing to mean what
    they say."""
    missing = sorted(name for name in set(WALKERS) | set(EXEMPT) if not (ROOT / name).is_file())
    assert not missing, f"listed modules that do not exist: {missing}"


def test_every_cohort_read_goes_through_the_chokepoint():
    """A module that queries Workspace.assignment_id without also filtering student_id is asking
    a class-level question, and a class-level question that sees a practice copy puts a teacher's
    own attempts in a student's gradebook. Source inspection, in the idiom of
    test_scoping.py::test_every_scoped_console_route_goes_through_one_of_the_two_lookups."""
    offenders = []
    for name in WALKERS:
        if name in EXEMPT:
            continue
        offenders.extend(f"{name}:{query}" for query in _offenders(ROOT / name))
    assert not offenders, (
        "cohort reads that do not go through workspaces.class_workspaces:\n  "
        + "\n  ".join(offenders)
        + "\n(a site needing its own joins composes class_workspace_clause(); repeating the "
          "practice condition inline is the thing this guard forbids)"
    )


def test_every_exempt_module_really_queries_workspaces():
    """Guards the exemptions: a name here matching no such query stops excusing anything."""
    hollow = []
    for name, why in sorted(EXEMPT.items()):
        if not _cohort_reads(ROOT / name):
            hollow.append(f"{name} ({why})")
    assert not hollow, (
        "exemptions excusing no cohort read -- delete them or the next one hides behind them: "
        + ", ".join(hollow)
    )


def test_the_walker_list_is_every_module_that_queries_workspaces_by_assignment():
    """A new module shows up here and somebody has to classify it -- the same reason
    test_problem_set_fence pins its practice-only list as a literal."""
    found = sorted(
        path.relative_to(ROOT).as_posix()
        for path in ROOT.rglob("*.py")
        if path.relative_to(ROOT).as_posix() != "workspaces.py" and _asks_about_a_cohort(path)
    )
    assert found == sorted(WALKERS), (
        "modules querying Workspace.assignment_id that nobody has classified: "
        f"{sorted(set(found) - set(WALKERS))}; listed but no longer querying: "
        f"{sorted(set(WALKERS) - set(found))}"
    )


# ── the chokepoint itself ──────────────────────────────────────────────────────────────

def test_the_chokepoint_offers_all_three_ways_in():
    """The guard above is only worth something if there is somewhere to send a cohort read."""
    from originalentry import workspaces

    missing = [name for name in CHOKEPOINT_NAMES
               if not callable(getattr(workspaces, name, None))]
    assert not missing, f"workspaces.py does not define: {missing}"


def test_the_chokepoint_is_the_only_place_the_practice_condition_is_written():
    """And the other half of "one query": nowhere else may name ``staff_practice`` in a filter.

    ``is_own_practice`` reads the attribute off a workspace object, which is the write gate's
    business and not a query; what must not exist is a second *query* condition, because a second
    one is how the nine sites drift apart and how one of them keeps counting a practice copy
    after the other eight stopped.
    """
    homes = sorted(
        path.relative_to(ROOT.parent).as_posix()
        for path in ROOT.rglob("*.py")
        if _practice_conditions(path)
    )
    assert homes == [CHOKEPOINT], f"Workspace.staff_practice is filtered on in {homes}"


# ── guards the guard ───────────────────────────────────────────────────────────────────

#: Every spelling of a cohort read that would really be used -- the two in the codebase today
#: plus the obvious third. The ``.in_`` and ``group_by`` shapes are the reason this scan looks for
#: the column in any form: an ``==``-only pattern sees neither, and would have left purge.py's
#: exemption excusing a query it could not find.
COHORT_SPELLINGS = (
    "rows = session.scalars(select(Workspace).where(Workspace.assignment_id == assignment.id))",
    "ids = session.scalars(select(Workspace.id)"
    ".where(Workspace.assignment_id.in_(assignment_ids)))",
    "counts = session.execute(db.select(Workspace.assignment_id, db.func.count())"
    ".group_by(Workspace.assignment_id))",
    "query = select(Workspace).filter(Workspace.assignment_id == found.id)",
    # The shape the first version of this guard let through: a cohort read that *joins* the
    # student's name onto each row. Three of the nine -- the progress table, the grading roster
    # and the archived-books list -- are written exactly like this.
    "rows = session.execute(select(Workspace, User).join(User, Workspace.student_id == User.id)"
    ".where(Workspace.assignment_id == assignment.id))",
    # ``filter_by`` names the column without naming the model, so it is invisible to every check
    # built on attribute access. Review found this spelling passing all three list tests in
    # silence, which is worse than a missing guard: the walker list did not flag it either, so a
    # new module could have carried it.
    "rows = db.session.scalars(db.select(Workspace)"
    ".filter_by(assignment_id=assignment.id, archived_at=None)).all()",
)

#: And the ones that must not be reported. The first two are per-person, the third goes through
#: the chokepoint, and the fourth composes its filter.
INNOCENT_SPELLINGS = (
    "ws = session.scalars(select(Workspace).where(Workspace.assignment_id == assignment.id,"
    " Workspace.student_id == student.id)).one_or_none()",
    "rows = session.execute(select(Workspace, Assignment)"
    ".join(Assignment, Workspace.assignment_id == Assignment.id)"
    ".where(Workspace.student_id == current_user.id))",
    "rows = class_workspaces(session, assignment)",
    "rows = session.execute(select(Workspace, User).join(User)"
    ".where(*class_workspace_clause(assignment)))",
    # The same filter_by spelling, per-person.
    "ws = db.session.scalars(db.select(Workspace)"
    ".filter_by(assignment_id=assignment.id, student_id=current_user.id)).one_or_none()",
    # ``staff/views._workspace_or_404``: one named row, which is how a teacher opens their own
    # practice copy from the console. Reporting it would push somebody into excluding practice
    # copies from the one query that has to find them.
    "ws = db.session.scalars(db.select(Workspace)"
    ".filter_by(public_id=public_id, assignment_id=assignment.id, archived_at=None))",
    # Task 6 has to be able to *make* a practice copy. A constructor is a write, not a query.
    "ws = Workspace(assignment_id=assignment.id, student_id=teacher.id, staff_practice=True)",
)

#: What the one-home scan must catch, and must not. Both spellings of a second definition, and
#: the three ways ``staff_practice`` is legitimately mentioned.
SECOND_DEFINITIONS = (
    "query = select(Workspace).where(Workspace.staff_practice.is_(False))",
    "rows = db.select(Workspace).filter_by(assignment_id=a.id, staff_practice=False)",
)
LEGITIMATE_MENTIONS = (
    "ws = Workspace(assignment_id=assignment.id, student_id=teacher.id, staff_practice=True)",
    'flagged = getattr(workspace, "staff_practice", False)',
    "staff_practice: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)",
)


def test_the_scan_would_catch_a_cohort_read_in_any_of_its_spellings(tmp_path):
    """Guards the guard, which otherwise cannot fail.

    A green guard over the one failure the spec calls unrecoverable is worse than no guard,
    because nobody looks again. Every spelling below is one somebody would plausibly write; the
    scan has to report all four.
    """
    for source in COHORT_SPELLINGS:
        offender = tmp_path / "offender.py"
        offender.write_text(source + "\n")
        assert _offenders(offender), f"the scan did not catch: {source}"


def test_the_one_home_scan_sees_a_second_definition_and_not_a_practice_copy_being_made(tmp_path):
    """Guards the one-home test in both directions.

    It reads the syntax tree rather than matching the text ``staff_practice =``, because text
    cannot tell a filter from a constructor -- and Task 6 has to construct a practice copy. Text
    matching would either miss ``filter_by(staff_practice=False)`` or fail on Task 6's own code,
    and the second is worse: the obvious repair is to delete the test.
    """
    for source in SECOND_DEFINITIONS:
        offender = tmp_path / "offender.py"
        offender.write_text(source + "\n")
        assert _practice_conditions(offender), f"a second definition slipped through: {source}"
    for source in LEGITIMATE_MENTIONS:
        innocent = tmp_path / "innocent.py"
        innocent.write_text(source + "\n")
        assert not _practice_conditions(innocent), f"reported as a second definition: {source}"


def test_the_clause_cannot_widen_to_every_assignment_by_accident():
    """``class_workspace_clause()`` with the argument left off used to return the other two
    conditions and quietly drop the assignment, which is one token from correct and no longer a
    question about one class: it puts another section's workspaces into a class list, which is
    what ``_scoped()`` and ``may_see_section`` exist to prevent. Nothing could notice -- the guard
    only checks that the call appears, and the exclusion fixture held a single assignment.

    So the omission is a ``TypeError`` now, and the one caller that really does ask across every
    assignment says so with a sentinel nobody writes by accident.
    """
    from originalentry import workspaces

    with pytest.raises(TypeError):
        workspaces.class_workspace_clause()

    assert len(workspaces.class_workspace_clause(7)) == 3, "an assignment id adds a condition"
    assert len(workspaces.class_workspace_clause(workspaces.ALL_ASSIGNMENTS)) == 2

    # And the sentinel must not be a way into the other two, which answer about one assignment.
    for ask in (workspaces.class_workspaces, workspaces.class_workspace_ids):
        with pytest.raises(ValueError):
            ask(None, workspaces.ALL_ASSIGNMENTS)


def test_the_scan_does_not_cry_wolf(tmp_path):
    """The other direction, and the one that would break teaching rather than privacy: reporting
    a per-person query would push somebody into excluding practice copies from it, and a teacher
    could no longer reach their own copy."""
    for source in INNOCENT_SPELLINGS:
        innocent = tmp_path / "innocent.py"
        innocent.write_text(source + "\n")
        assert not _offenders(innocent), f"the scan cried wolf over: {source}"
