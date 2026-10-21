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

**What the scan reports.** Any statement that queries workspaces by assignment --
``Workspace.assignment_id`` in any form, or ``filter_by(assignment_id=...)`` -- unless it goes
through the chokepoint, sits in an ``EXEMPT`` module, or sits in a function named in
``PER_PERSON``. Nothing is inferred about the query itself. The default is **report**.

**Why the default is report, and not "report unless this looks like a cohort read".** Three
earlier rounds of this guard tried to decide, from the syntax tree, whether a statement pinned a
single person or a single row, and so could be excused. Each round closed the previous round's
hole, each time in the too-permissive direction:

1. asking whether ``student_id`` was *mentioned* excused ``Workspace.student_id == User.id``, a
   join that filters nobody, and with it the progress table, the grading roster and the
   archived-books list -- three of the screens a teacher actually looks at;
2. asking whether a ``public_id`` keyword appeared anywhere excused two cohort reads that reach a
   class through the *assignment's* public id;
3. asking only whether the column was pinned excused ``public_id != ws.public_id`` ("the rest of
   the class"), ``public_id > cursor`` (a paginated roster) and ``student_id != current_user.id``
   -- the last of which still admits a **co-instructor's** practice copy, because a practice copy
   is per-owner and nothing limits an assignment to one teacher.

And a fourth set was open after round 3, each shape the *same SQL* as one round 3 had just closed:
``~(Workspace.student_id == current_user.id)``, ``not_(Workspace.public_id == ws.public_id)``,
``or_(mine, the_whole_class)``, a pin sitting in an ``order_by`` or a nested subquery, a name bound
to a subquery one line earlier and passed to ``in_``, and a cohort leg ``union``ed onto a
per-person one.

Every one of those predicates was an ``ast.walk`` existence check -- *does some node in this
statement look like a pin?* -- where the safe question is a property of the statement's whole
top-level boolean expression: *does this filter restrict the result to one row or one person?*
That depends on polarity, on position, and on values the tree cannot see. Enumerating operators
does not converge; an allowlist of audited call sites converges by construction, and it is the
pattern this guard already uses for ``EXEMPT`` and ``WALKERS``, and the pattern
``test_scoping.py`` uses for its own ``EXEMPT``/``ADMISSION_BLIND`` lists.

**Keyed by name, never by line number.** A line number drifts and a drifted entry silently excuses
the wrong statement, which is the failure mode of the whole class of mechanism this round removed.
``test_every_per_person_entry_is_a_live_per_person_query`` is what keeps an entry honest -- in the
idiom of ``test_scoping.py::test_every_exempt_name_is_a_real_route`` -- and it holds each entry to
**exactly one** such query in its function, so a second query appearing inside an allowlisted
function is somebody's decision rather than a free ride.
``test_every_per_person_entry_is_load_bearing`` is the other half: it removes each entry in turn
and requires the site to be reported without it, because asserting that a site is exempt *with*
its entry is the mechanism restating itself and can never fail.

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
           # The practice lifecycle (Task 3). It asks one question about workspaces by
           # assignment -- "does this one teacher already hold a live copy of it?" -- which is a
           # per-person read, and the opposite of a cohort one: it exists to *find* a practice
           # copy, so it must never be routed through the chokepoint.
           "services/practice.py",
           # Not in the task brief's literal, and found by the completeness test below rather
           # than by anybody's memory: `choose_company` queries (assignment, student), which is
           # a per-person read and so needs no exclusion -- but a module nobody classified is
           # exactly what that test exists to surface.
           "services/multicompany.py")

#: Whole modules that are not cohort reads, and why. Both are write paths with their own decisions.
EXEMPT = {
    "services/purge.py": "retention deletion must reach every row or it orphans FK records",
    "packs/migrate.py": "a migration archives practice copies (Task 6), it does not report them",
}

#: The audited per-person call sites: ``(module, function)`` -> which person or row it pins.
#:
#: A per-person query names one student or one workspace, so a practice copy only ever matches its
#: own owner and must **not** be excluded -- excluding it is how a teacher loses the way back into
#: their own copy. Every entry here was read off the function it names, and the reason says which
#: person or row that function restricts to. Seven sites, all of them small named functions.
#:
#: Adding an entry is the serious act in this file, and the only way to excuse a query from the
#: chokepoint. It means: *I read this function and the query cannot return a row belonging to
#: anybody but the named person.* An entry is not a way to quiet a red suite -- see the assertion
#: message in ``test_every_cohort_read_goes_through_the_chokepoint`` for the two repairs that are
#: not this one.
PER_PERSON = {
    ("services/assignments.py", "prerequisite_met"):
        "pins student_id to the student whose prerequisite is being judged",
    ("services/assignments.py", "open_workspace"):
        "pins student_id to the student whose live workspace is being opened",
    ("services/multicompany.py", "choose_company"):
        "pins student_id to the student making the choice",
    ("student/views.py", "home"):
        "pins student_id to current_user; assignment_id appears only as a join condition",
    ("student/views.py", "_live_workspace"):
        "pins student_id to current_user, for one assignment",
    ("services/practice.py", "_live_copy"):
        "pins student_id to the one teacher asking for their own practice copy, for one "
        "assignment; it must see an unflagged row too, because an account that worked the "
        "assignment as a student already occupies the live slot and that is what the opener "
        "refuses on",
    ("staff/views.py", "_workspace_or_404"):
        "pins public_id to the one workspace a teacher clicked, which is how they open their own "
        "practice copy from the console",
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
    ``filter_by(assignment_id=...)``.

    The detection side is deliberately **wide**, and stays wide now that the exemptions no longer
    try to narrow it. ``services/purge.py`` writes ``Workspace.assignment_id.in_(ids or [0])`` and
    ``staff/views.py`` names the column in a ``select``/``group_by`` pair with no comparison at
    all; an ``==``-only pattern would see neither, and
    ``test_every_exempt_module_really_queries_workspaces`` would then pass vacuously for purge --
    and that test is the only thing keeping purge's exemption honest.
    """
    return (_is_workspace_column(node, "assignment_id")
            or "assignment_id" in _filter_by_keywords(node))


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
    """One statement that queries workspaces by assignment, and where to find it."""

    line: int
    function: str | None
    source: str
    statement: ast.stmt

    def __str__(self) -> str:
        where = self.function or "<module>"
        return f"{where}:{self.line}  {self.source.splitlines()[0].strip()}"


def _module_key(path: pathlib.Path) -> str:
    """How ``PER_PERSON`` and ``EXEMPT`` spell this file, or its bare name if it is outside the
    package -- which is how the tmp_path cases below get judged with nothing allowlisted."""
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.name


def _enclosing_function(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str | None:
    """The innermost ``def`` this node sits in, which is how an allowlist entry is addressed.

    The innermost one, so a closure cannot borrow its enclosing function's entry. ``None`` for a
    statement in a module body, and ``None`` matches no entry.
    """
    current: ast.AST | None = node
    while current is not None:
        if isinstance(current, ast.FunctionDef | ast.AsyncFunctionDef):
            return current.name
        current = parents.get(current)
    return None


def _assignment_queries(path: pathlib.Path) -> list[Query]:
    """Every statement in this file that queries workspaces by assignment."""
    return _assignment_queries_in(path.read_text(), filename=str(path))


def _assignment_queries_in(text: str, *, filename: str = "<source>") -> list[Query]:
    """The same scan over source text, so a test can hand it one function's source.

    One record per enclosing *statement*: the statement is the unit a query is written in --
    ``session.scalars(select(Workspace).where(...))`` is one statement across six lines -- and it
    is the unit a reviewer reads when deciding whether a site belongs in ``PER_PERSON``. Judging a
    single line instead would read ``Workspace.assignment_id == assignment.id,`` on its own.
    """
    tree = ast.parse(text, filename=filename)
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
            statement.lineno, _enclosing_function(statement, parents),
            ast.get_source_segment(text, statement) or "", statement)
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


def _cohort_reads(path: pathlib.Path, *, audited: dict | None = None) -> list[Query]:
    """The queries in this file that are nobody's audited per-person lookup.

    Which is to say: everything the scan found, less the statements sitting in a function named in
    the allowlist. No judgement is made about the query's own text -- that judgement is what three
    rounds of holes were made of, and it now lives in the allowlist, where a person made it once
    and a test keeps it live.

    ``audited`` defaults to ``PER_PERSON`` and is a parameter only so a test can ask what the scan
    would say with one entry taken away, which is the only way to show an entry is load-bearing:
    with the entry in place the site is exempt *by construction*, so asserting that proves nothing.
    """
    module = _module_key(path)
    audited = PER_PERSON if audited is None else audited
    return [q for q in _assignment_queries(path) if (module, q.function) not in audited]


def _offenders(path: pathlib.Path, *, audited: dict | None = None) -> list[Query]:
    """Cohort reads in this file that do not go through the chokepoint."""
    return [q for q in _cohort_reads(path, audited=audited)
            if not any(call in q.source for call in CHOKEPOINT_CALLS)]


def _functions_named(path: pathlib.Path, name: str) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Every ``def`` of this name in the file, at any depth. More than one is ambiguous: the scan
    would exempt both, and the allowlist entry cannot say which it audited."""
    tree = ast.parse(path.read_text(), filename=str(path))
    return [node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name]


def test_every_walker_is_a_real_file():
    """A walker naming no file guards nothing, an exempt name matching no file excuses nothing, and
    an allowlist entry in a module that does not exist excuses nothing either. Rename a module and
    this fails, rather than the lists quietly ceasing to mean what they say."""
    listed = set(WALKERS) | set(EXEMPT) | {module for module, _ in PER_PERSON}
    missing = sorted(name for name in listed if not (ROOT / name).is_file())
    assert not missing, f"listed modules that do not exist: {missing}"


def test_every_cohort_read_goes_through_the_chokepoint():
    """A module that queries Workspace.assignment_id outside an audited per-person call site is
    asking a class-level question, and a class-level question that sees a practice copy puts a
    teacher's own attempts in a student's gradebook. Source inspection, in the idiom of
    test_scoping.py::test_every_scoped_console_route_goes_through_one_of_the_two_lookups."""
    offenders = []
    for name in WALKERS:
        if name in EXEMPT:
            continue
        offenders.extend(f"{name}:{query}" for query in _offenders(ROOT / name))
    assert not offenders, (
        "workspace-by-assignment queries that neither go through workspaces.class_workspaces nor "
        "sit in an audited per-person call site:\n  "
        + "\n  ".join(offenders)
        + "\n(a site needing its own joins composes class_workspace_clause(); repeating the "
          "practice condition inline is the thing this guard forbids)"
        # Said here because this is the sentence somebody reads at 5pm with a red suite. If one
        # of these really is a single-row or per-person lookup, the chokepoint is the WRONG repair:
        # it carries staff_practice.is_(False), so routing a per-person lookup through it 404s a
        # teacher out of their own practice copy -- the one thing this feature exists to give them.
        + "\nTwo repairs, and only two. If it is a class-level question, route it through the "
          "chokepoint. If it is really a per-person or single-row lookup, do NOT route it through "
          "the chokepoint -- that excludes practice copies and locks a teacher out of their own "
          "copy -- but put it in its own named function and add a PER_PERSON entry saying which "
          "person or row it pins, having read the whole statement and satisfied yourself that it "
          "cannot return anybody else's row. An entry is an audit, not a mute button."
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


def test_every_per_person_entry_is_a_live_per_person_query():
    """Guards the allowlist, which is now the only thing that excuses a query.

    In the idiom of ``test_scoping.py::test_every_exempt_name_is_a_real_route``: an entry naming a
    function that has been renamed or deleted excuses nothing, and would sit here reading like
    cover long after it stopped being any. So an entry must name a function that exists, is defined
    exactly once, sits in a module this guard walks and does not exempt wholesale, and still holds
    **exactly one** workspace-by-assignment query.

    Exactly one, rather than at least one, is the part that keeps the entry's granularity honest:
    the entry is addressed to a function but was written about a statement, and a second query
    appearing in the same function would inherit the excuse without anybody reading it. If that
    second query is a class-level question it belongs at the chokepoint; if it is genuinely a
    second per-person lookup it belongs in its own named function with its own entry and its own
    reason. Either way somebody classifies it, which is the whole point.
    """
    problems = []
    for (module, function), why in sorted(PER_PERSON.items()):
        where = f"{module}::{function}"
        if module in EXEMPT:
            problems.append(f"{where} -- the whole module is already EXEMPT, so this excuses "
                            "nothing; delete one of the two")
            continue
        if module not in WALKERS:
            problems.append(f"{where} -- not a module this guard walks, so this excuses nothing")
            continue
        path = ROOT / module
        if not path.is_file():  # pragma: no cover - test_every_walker_is_a_real_file says it first
            problems.append(f"{where} -- no such module")
            continue
        definitions = _functions_named(path, function)
        if not definitions:
            problems.append(f"{where} -- no such function ({why})")
            continue
        if len(definitions) > 1:
            lines = [node.lineno for node in definitions]
            problems.append(f"{where} -- defined {len(definitions)} times, at lines {lines}; the "
                            "entry cannot say which one it audited and the scan would exempt both")
            continue
        queries = [q for q in _assignment_queries(path) if q.function == function]
        if not queries:
            problems.append(f"{where} -- no longer queries workspaces by assignment, so it needs "
                            f"no exemption ({why})")
        elif len(queries) > 1:
            lines = [q.line for q in queries]
            problems.append(f"{where} -- now holds {len(queries)} such queries, at lines {lines}; "
                            f"the entry was written about one of them ({why})")
    assert not problems, (
        "PER_PERSON entries that are not live per-person queries:\n  " + "\n  ".join(problems)
        + "\nAn entry that excuses nothing is worse than no entry: it reads like cover."
    )


def test_every_per_person_entry_is_load_bearing():
    """Each entry really is what excuses its site, read off the real code.

    The obvious test here -- "assert the allowlisted sites are not reported" -- is a tautology,
    and writing it was my first mistake this round: ``_cohort_reads`` drops allowlisted functions by
    construction, so that assertion is the mechanism restating itself and could never fail. A green
    guard over the one failure the spec calls unrecoverable is the thing this file warns about most.

    The claim that can fail is the inverse: take the entry away and the site **is** reported. That
    says the entry carries weight today, so an entry that has quietly stopped mattering -- because
    the function was rewritten to go through the chokepoint, say -- shows up here instead of sitting
    in the list looking like cover. Together with
    ``test_every_per_person_entry_is_a_live_per_person_query``, which holds each entry to exactly
    one live query, that is the whole of what keeps the allowlist from decaying.

    And the direction that matters most is the one these six protect: a reported per-person site
    pushes the next developer towards the chokepoint, which carries ``staff_practice.is_(False)``,
    and a teacher would be 404'd out of their own practice copy.
    """
    idle = []
    for (module, function), why in sorted(PER_PERSON.items()):
        without = {key: text for key, text in PER_PERSON.items() if key != (module, function)}
        reported = [q for q in _offenders(ROOT / module, audited=without)
                    if q.function == function]
        if not reported:
            idle.append(f"{module}::{function} ({why})")
    assert not idle, (
        "PER_PERSON entries that excuse nothing -- with the entry removed the scan still does not "
        "report the site, so the entry is carrying no weight and should go:\n  " + "\n  ".join(idle)
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

#: Every spelling of a cohort read that would really be used. The first group is the record of what
#: rounds 1 to 3 found leaking: each was exempt in silence, each is a shape somebody would write,
#: and each is kept as a regression case. Under the allowlist they do not merely report because an
#: operator was enumerated -- they report because nothing excuses them, which is the stronger claim.
COHORT_SPELLINGS = (
    "rows = session.scalars(select(Workspace).where(Workspace.assignment_id == assignment.id))",
    "ids = session.scalars(select(Workspace.id)"
    ".where(Workspace.assignment_id.in_(assignment_ids)))",
    "counts = session.execute(db.select(Workspace.assignment_id, db.func.count())"
    ".group_by(Workspace.assignment_id))",
    "query = select(Workspace).filter(Workspace.assignment_id == found.id)",
    # Round 1. A cohort read that *joins* the student's name onto each row. Three of the nine --
    # the progress table, the grading roster and the archived-books list -- are written like this,
    # and the first version of this guard passed all three because the words "student_id" appeared.
    "rows = session.execute(select(Workspace, User).join(User, Workspace.student_id == User.id)"
    ".where(Workspace.assignment_id == assignment.id))",
    # Round 1. ``filter_by`` names the column without naming the model, so it is invisible to every
    # check built on attribute access. Review found this spelling passing all three list tests in
    # silence, which is worse than a missing guard: the walker list did not flag it either, so a
    # new module could have carried it.
    "rows = db.session.scalars(db.select(Workspace)"
    ".filter_by(assignment_id=assignment.id, archived_at=None)).all()",
    # Round 2. Reaching the class through the *assignment's* public id -- which is how a URL does
    # it throughout this codebase. Both were exempted by a ``public_id`` keyword that belonged to
    # another model, the hole review found in the fix for the hole above.
    "rows = session.scalars(select(Workspace).where("
    "Workspace.assignment_id.in_(select(Assignment.id).filter_by(public_id=pid)))).all()",
    "rows = session.execute(select(Workspace)"
    ".join(Assignment, Workspace.assignment_id == Assignment.id)"
    ".filter_by(public_id=pid)).all()",
    # Round 3. Mentioning a key column is not being keyed to one row. Each of these is a cohort
    # read written with the very column that used to exempt it.
    "rest = session.scalars(select(Workspace).where("
    "Workspace.assignment_id == assignment.id, Workspace.public_id != ws.public_id)).all()",
    "page = session.scalars(select(Workspace).where("
    "Workspace.assignment_id == assignment.id, Workspace.public_id > cursor)).all()",
    # The worst of them: it still admits a *co-instructor's* practice copy, because a practice
    # copy is per-owner and nothing limits an assignment to one teacher.
    "others = session.scalars(select(Workspace).where("
    "Workspace.assignment_id == assignment.id, Workspace.student_id != current_user.id)).all()",
    "nobody = session.scalars(db.select(Workspace).filter_by("
    "assignment_id=assignment.id, student_id=None)).all()",
    "everyone = session.scalars(select(Workspace).where("
    "Workspace.assignment_id == assignment.id, Workspace.student_id.in_(select(User.id)))).all()",
    # Round 4, and the reason the inferential exemptions are gone. Every shape below is the *same
    # SQL* as one of the shapes above, written with an ``==`` that an ``ast.walk`` existence check
    # finds and reads as a pin. The first two are literally the round-3 spellings under a negation.
    "mine = session.scalars(select(Workspace).where(Workspace.assignment_id == assignment.id,"
    " ~(Workspace.student_id == current_user.id))).all()",
    "rest = session.scalars(select(Workspace).where(Workspace.assignment_id == assignment.id,"
    " not_(Workspace.public_id == ws.public_id))).all()",
    # Polarity again, the other way: "mine, OR anybody who has handed in" is a cohort read with a
    # genuine per-person pin inside it.
    "both = session.scalars(select(Workspace).where(Workspace.assignment_id == assignment.id)"
    ".where(or_(Workspace.student_id == current_user.id,"
    " Workspace.submitted_at.is_not(None)))).all()",
    # Position. The pin is in an ``order_by`` -- floating your own row to the top of a roster --
    # and in a nested subquery, and neither narrows the rows the statement returns.
    "roster = session.scalars(select(Workspace).where(Workspace.assignment_id == assignment.id)"
    ".order_by(Workspace.student_id == current_user.id)).all()",
    "peers = session.scalars(select(Workspace).where(Workspace.assignment_id == assignment.id,"
    " Workspace.pack_version_id == select(Workspace.pack_version_id).where("
    "Workspace.student_id == current_user.id).scalar_subquery())).all()",
    # A value the tree cannot see: ``enrolled`` is a subquery bound one line earlier, so an
    # ``in_`` that refuses a literal ``select(...)`` argument but accepts a name is no defence.
    "enrolled = select(User.id).where(User.section_id == assignment.section_id)\n"
    "everyone = session.scalars(select(Workspace).where("
    "Workspace.assignment_id == assignment.id, Workspace.student_id.in_(enrolled))).all()",
    # And a per-person leg with a cohort leg welded onto it, in one statement.
    "rows = session.scalars(select(Workspace).where(Workspace.assignment_id == assignment.id,"
    " Workspace.student_id == current_user.id)"
    ".union(select(Workspace).where(Workspace.assignment_id == assignment.id))).all()",
)

#: And the ones that must not be reported. There are only three, and none of them is an inference
#: about a query's text: two go through the chokepoint, and the third is not a query at all.
#: Everything the old ``INNOCENT_SPELLINGS`` list held besides these was a per-person *shape* fed
#: to a predicate that no longer exists; a real per-person site is excused by name now, and
#: ``test_every_per_person_entry_is_load_bearing`` asserts that against the functions it names.
INNOCENT_SPELLINGS = (
    "rows = class_workspaces(session, assignment)",
    "rows = session.execute(select(Workspace, User).join(User)"
    ".where(*class_workspace_clause(assignment)))",
    # Task 6 has to be able to *make* a practice copy, and a constructor is a write, not a query.
    # This is a case about the detection side -- ``_queries_an_assignment`` matches an
    # ``assignment_id`` keyword only inside ``filter_by`` -- and it is the one direction of the
    # detection side that an allowlist cannot cover, because a constructor sits in whatever
    # function Task 6 writes it in.
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
    because nobody looks again. Every spelling below is one somebody would plausibly write, and
    every one of them is a shape that was exempt in silence at some point in this guard's history.
    """
    for source in COHORT_SPELLINGS:
        offender = tmp_path / "offender.py"
        offender.write_text(source + "\n")
        assert _offenders(offender), f"the scan did not catch: {source}"


def test_the_allowlist_is_addressed_by_name_and_not_by_position(tmp_path):
    """The allowlist's own mechanism, in both directions.

    An entry excuses the queries in the function it names, in the module it names, and nothing
    else. Two things are being pinned: that a module-and-function key really does reach into a
    function body at all, and that the same query text in a function the allowlist does not name
    is still reported. The second is what makes an entry a statement about audited code rather
    than about a shape -- the property the three rounds of inferential exemptions never had.
    """
    module = tmp_path / "views.py"
    module.write_text(
        "def audited():\n"
        "    return session.scalars(select(Workspace).where(\n"
        "        Workspace.assignment_id == assignment.id,\n"
        "        Workspace.student_id == current_user.id)).one_or_none()\n"
        "\n"
        "def unaudited():\n"
        "    return session.scalars(select(Workspace).where(\n"
        "        Workspace.assignment_id == assignment.id,\n"
        "        Workspace.student_id == current_user.id)).one_or_none()\n"
    )
    found = {q.function for q in _assignment_queries(module)}
    assert found == {"audited", "unaudited"}, f"the scan did not place both queries: {found}"

    audited = {(_module_key(module), "audited"): "test fixture"}
    reported = {q.function for q in _offenders(module, audited=audited)}
    assert reported == {"unaudited"}, (
        "an entry must excuse the function it names and no other; "
        f"reported {sorted(reported)}"
    )


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
    """The direction that would break teaching rather than privacy: reporting a query that must
    see a practice copy pushes somebody into excluding practice copies from it, and a teacher could
    no longer reach their own copy. The real sites are covered by
    ``test_every_per_person_entry_is_load_bearing``; these are the spellings nobody has written
    yet."""
    for source in INNOCENT_SPELLINGS:
        innocent = tmp_path / "innocent.py"
        innocent.write_text(source + "\n")
        assert not _offenders(innocent), f"the scan cried wolf over: {source}"
