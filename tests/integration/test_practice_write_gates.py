"""Who may write to a workspace, and the two gates that have to agree about it.

A teacher works their own assignment the way a student would, in a private practice copy. The
copy is an ordinary workspace whose ``student_id`` is the teacher's own and whose
``staff_practice`` flag is set, and the whole of the permission change is one function --
``workspaces.is_own_practice`` -- consulted by **both** of the application's write gates:

* ``decorators.workspace_view`` sets ``g.read_only``, which the chapter-problem routes and the
  journal screens consult through ``_guard_writable``;
* ``services.write._check_gates`` independently refuses any actor who is not the owning student,
  and every practice-set write -- entries, dispositions, posting, statements, submit -- goes
  through it.

The two gates disagreeing is the failure mode these tests exist for. Relax only the decorator and
chapter problems become writable while every practice-set write is still refused: a feature that
is half working, whose broken half takes an afternoon to find. So the write path is tested
directly *and* through the routes, and a source-inspection test pins that neither gate carries a
definition of its own.

The anti-goal is tested as hard as the goal: a practice copy must be the only thing this relaxes.
A teacher must not be able to write to a student's workspace, nor to another teacher's copy.
"""

from __future__ import annotations

import contextlib
import inspect
import pathlib
import re
from datetime import UTC, date, datetime

import pytest
from flask import g
from originalentry import decorators
from originalentry.forms.entries import EntryCommand, LineCommand
from originalentry.models import (
    KIND_REGULAR,
    ROLE_INSTRUCTOR,
    Assignment,
    ContentPack,
    JournalEntry,
    PackVersion,
    Section,
    SectionStaff,
    User,
    Variant,
    Workspace,
)
from originalentry.packs import schema
from originalentry.packs.importer import import_answer_keys, import_content
from originalentry.problems import importing
from originalentry.services import WriteRefused, workspace_write
from originalentry.services import write as write_service
from originalentry.services.accommodations import close_for
from originalentry.services.entries import record_entry
from originalentry.services.posting import active_posted_entry_ids
from originalentry.workspaces import is_own_practice
from sqlalchemy import func, select

from tests.packs import testco_alpha
from tests.unit.test_chapter_file import VALID

pytestmark = pytest.mark.db

LAST_WEEK = datetime(2026, 1, 8, 23, 59, tzinfo=UTC)

#: A right answer to the chapter's first problem, in the form the problem screen posts.
RIGHT = {
    "line-1-account": "150", "line-1-debit": "4800.00", "line-1-credit": "",
    "line-2-account": "101", "line-2-debit": "", "line-2-credit": "1800.00",
    "line-3-account": "201", "line-3-debit": "", "line-3-credit": "3000.00",
}


# ── the world ──────────────────────────────────────────────────────────────────────────

def _user(email: str, *, role: str | None = None) -> User:
    user = User(email=email, given_name="Ada", family_name="Sowande")
    if role is not None:
        user.role = role
    return user


def _slug_of(session, pack_version_id: int) -> str:
    version = session.get(PackVersion, pack_version_id)
    return session.get(ContentPack, version.content_pack_id).slug


@pytest.fixture
def world(session):
    """A practice-set assignment with a student's workspace and the teacher's practice copy.

    Both workspaces are on the *same* assignment, which is the real shape: the teacher is working
    the assignment they set. The unique index on (assignment, student) does not collide because a
    practice copy's ``student_id`` is the teacher's own id.
    """
    pack_version = import_content(session, schema.load_pack(testco_alpha.PACK),
                                  source_sha256="prac" + "0" * 60)
    import_answer_keys(session, pack_version, {"A": schema.load_answer_key(testco_alpha.KEY_A)})
    variant_id = session.scalars(
        select(Variant.id).where(Variant.pack_version_id == pack_version.id)).first()

    section = Section(name="Sec", join_code="prac-join")
    teacher = _user("gates-teacher@example.edu", role=ROLE_INSTRUCTOR)
    other_teacher = _user("gates-other-teacher@example.edu", role=ROLE_INSTRUCTOR)
    student = _user("gates-student@example.edu")
    session.add_all([section, teacher, other_teacher, student])
    session.flush()
    session.add_all([
        SectionStaff(section_id=section.id, user_id=teacher.id),
        SectionStaff(section_id=section.id, user_id=other_teacher.id),
    ])
    assignment = Assignment(section_id=section.id, title="December", company_policy="fixed",
                            fixed_pack_version_id=pack_version.id)
    session.add(assignment)
    session.flush()

    student_workspace = Workspace(assignment_id=assignment.id, student_id=student.id,
                                  pack_version_id=pack_version.id, variant_id=variant_id,
                                  status="in_progress")
    practice = Workspace(assignment_id=assignment.id, student_id=teacher.id,
                         pack_version_id=pack_version.id, variant_id=variant_id,
                         status="in_progress", staff_practice=True)
    session.add_all([student_workspace, practice])
    session.flush()
    return {
        "teacher": teacher, "other_teacher": other_teacher, "student": student,
        "assignment": assignment, "practice": practice,
        "student_workspace": student_workspace,
        "slug": _slug_of(session, pack_version.id),
    }


@pytest.fixture
def teacher(world):
    return world["teacher"]


@pytest.fixture
def other_teacher(world):
    return world["other_teacher"]


@pytest.fixture
def student(world):
    return world["student"]


@pytest.fixture
def assignment(world):
    return world["assignment"]


@pytest.fixture
def practice(world):
    return world["practice"]


@pytest.fixture
def student_workspace(world):
    return world["student_workspace"]


@pytest.fixture
def problem_practice(session, world):
    """The same teacher's practice copy of a *chapter problem set*.

    A second kind of pack, because the two gates are reached by different routes for the two kinds
    and "both kinds work" is a claim this suite has to be able to fail.
    """
    version = importing.import_chapter(session, VALID)
    section = Section(name="Chapter sec", join_code="prac-chap")
    session.add(section)
    session.flush()
    session.add(SectionStaff(section_id=section.id, user_id=world["teacher"].id))
    assignment = Assignment(section_id=section.id, title="Chapter 3", company_policy="fixed",
                            fixed_pack_version_id=version.id, problems_required=2)
    session.add(assignment)
    session.flush()
    variant_id = session.scalars(
        select(Variant.id).where(Variant.pack_version_id == version.id)).first()
    ws = Workspace(assignment_id=assignment.id, student_id=world["teacher"].id,
                   pack_version_id=version.id, variant_id=variant_id, status="in_progress",
                   staff_practice=True)
    session.add(ws)
    session.flush()
    return {"workspace": ws, "slug": _slug_of(session, version.id), "assignment": assignment}


# ── the write path, directly ───────────────────────────────────────────────────────────

def _command(client_key: str) -> EntryCommand:
    return EntryCommand(
        journal_key="general",
        kind=KIND_REGULAR,
        document_ref="INV-1",
        entry_date=date(2026, 12, 2),
        description=None,
        lines=[
            LineCommand(account_number="112", party_code="C-ONE",
                        debit_cents=120_000, credit_cents=0),
            LineCommand(account_number="401", party_code=None,
                        debit_cents=0, credit_cents=120_000),
        ],
        client_key=client_key,
    )


def _record_entry_through(session, workspace, actor, *, client_key="practice-entry"):
    """One real write through the single write entry point, in the idiom of ``student.views``."""
    command = _command(client_key)
    return workspace_write(
        session, workspace.public_id, actor,
        activity_kind="save",
        mutate=lambda s, ws: record_entry(s, ws, command),
        detail={"journal": "general", "client_key": command.client_key},
    )


def _entries(session, workspace) -> int:
    return session.execute(
        select(func.count()).select_from(JournalEntry).where(
            JournalEntry.workspace_id == workspace.id)
    ).scalar_one()


def test_a_teacher_may_write_to_their_own_practice_copy_through_the_entry_path(
    session, teacher, practice
):
    """Review Focus 1, and the whole point: this is the gate the decorator does not control.

    Every practice-set write -- entries, dispositions, posting, statements, submit -- goes through
    ``workspace_write``, whose ``_check_gates`` refuses any non-student actor.
    """
    _record_entry_through(session, practice, teacher)  # must not raise

    assert _entries(session, practice) == 1


def test_a_teacher_may_not_write_to_a_students_workspace(session, teacher, student_workspace):
    """The anti-goal. Relaxing the gate for a practice copy must not relax it for anything else.

    Nothing is asserted after the refusal, here or in any of these tests: ``workspace_write`` rolls
    the session back on its way out, so a count taken afterwards is a count of a world that no
    longer exists and would read as zero whatever the gate had done.
    """
    with pytest.raises(WriteRefused):
        _record_entry_through(session, student_workspace, teacher)


def test_a_teacher_may_not_write_to_another_teachers_practice_copy(
    session, other_teacher, practice
):
    """``staff_practice`` is not a public door: it is the owner's own copy, and nobody else's."""
    with pytest.raises(WriteRefused):
        _record_entry_through(session, practice, other_teacher)


def test_a_student_is_unaffected(session, student, student_workspace):
    """Guards the change from the inside: the ordinary path must behave exactly as before."""
    _record_entry_through(session, student_workspace, student)

    assert _entries(session, student_workspace) == 1


def test_a_practice_copy_ignores_the_deadline(session, teacher, student, practice,
                                              student_workspace, assignment):
    """``_check_gates`` refuses on ``accommodations.close_for``. A teacher preparing next term's
    assignment works a copy whose deadline has not opened, or has passed.

    The student on the same assignment is refused in the same test, so that a deadline which was
    never actually shut cannot make the teacher's half pass for the wrong reason. The refusal comes
    last because ``workspace_write`` rolls the session back on its way out, which would undo the
    deadline and both workspaces along with it.
    """
    assignment.due_at = LAST_WEEK
    session.flush()
    assert close_for(session, student_workspace) == LAST_WEEK, "the window was never shut"

    _record_entry_through(session, practice, teacher)  # no refusal
    assert _entries(session, practice) == 1

    with pytest.raises(WriteRefused):
        _record_entry_through(session, student_workspace, student)


def test_a_practice_copy_is_still_read_only_once_submitted(session, teacher, practice):
    """Submitting is part of the student experience they are checking, and a submitted copy reads
    as a student's does. Start over is how they get a writable one back."""
    practice.status = "submitted"
    session.flush()

    with pytest.raises(WriteRefused):
        _record_entry_through(session, practice, teacher)


def test_a_practice_copy_still_waits_for_a_variant(session, teacher, practice):
    """A manual-variant assignment the instructor has not handed out yet has nothing to work on,
    and that is as true of their own copy as of a student's."""
    practice.variant_id = None
    session.flush()

    with pytest.raises(WriteRefused) as refused:
        _record_entry_through(session, practice, teacher)

    from originalentry import messages
    assert refused.value.message == messages.WAITING_FOR_VARIANT


# ── the rule itself ────────────────────────────────────────────────────────────────────

def test_is_own_practice_is_false_for_a_workspace_that_is_not_a_practice_copy(
    teacher, student_workspace
):
    assert is_own_practice(student_workspace, teacher) is False


def test_is_own_practice_is_true_only_for_the_owner(teacher, other_teacher, practice):
    assert is_own_practice(practice, teacher) is True
    assert is_own_practice(practice, other_teacher) is False


def test_is_own_practice_survives_a_missing_workspace_and_a_missing_actor(teacher, practice):
    """Load-bearing, and not obvious. The durable audit hook in ``app._register_audit`` runs on
    **every** response, including the many requests that never set ``g.workspace``, and it wraps
    its body in ``except Exception`` because "logging must never turn a good response into an
    error". An ``AttributeError`` on ``None.staff_practice`` would be swallowed there and the
    whole audit trail would stop recording, silently.
    """
    assert is_own_practice(None, teacher) is False
    assert is_own_practice(practice, None) is False
    assert is_own_practice(None, None) is False


# ── the other gate ─────────────────────────────────────────────────────────────────────

@contextlib.contextmanager
def _capturing(app):
    """What ``workspace_view`` put on ``g`` for the request just made.

    Registered and removed around the call rather than read off ``g`` afterwards: the test harness
    holds one app context open for the whole test, so a stale value from an earlier request would
    read as this request's answer.
    """
    seen: dict[str, object] = {}

    def _capture(response):
        seen["read_only"] = getattr(g, "read_only", None)
        return response

    app.after_request_funcs.setdefault(None, []).append(_capture)
    try:
        yield seen
    finally:
        app.after_request_funcs[None].remove(_capture)


def test_g_read_only_is_false_on_a_practice_copy_and_true_on_a_students(
    app, client, teacher, practice, student_workspace, world
):
    """The other gate. Both must agree, or the problem screens and the journal screens disagree
    about whether the same person may type."""
    client.sign_in(teacher)
    slug = world["slug"]

    with _capturing(app) as seen:
        client.get(f"/w/{practice.public_id}/{slug}/")
        on_practice = seen["read_only"]
        client.get(f"/w/{student_workspace.public_id}/{slug}/")
        on_a_student = seen["read_only"]

    assert on_practice is False, "the teacher cannot type in their own practice copy"
    assert on_a_student is True, "the teacher can type in a student's books"


def test_neither_gate_decides_it_alone(app):
    """Source inspection: both ``decorators.workspace_view`` and ``write._check_gates`` must name
    ``is_own_practice``. One definition, two callers -- a second definition is how they drift."""
    for gate in (decorators.workspace_view, write_service._check_gates):
        source = inspect.getsource(gate)
        assert "is_own_practice" in source, (
            f"{gate.__module__}.{gate.__qualname__} decides who may write without consulting the "
            "one definition"
        )


def test_the_rule_is_written_once(app):
    """And the other half of one definition: nowhere else may define it."""
    root = pathlib.Path(decorators.__file__).parent
    homes = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*.py")
        if re.search(r"^def is_own_practice\b", path.read_text(), re.MULTILINE)
    )

    assert homes == ["workspaces.py"], f"is_own_practice is defined in {homes}"


# ── both kinds, through the routes ─────────────────────────────────────────────────────

def _text(response) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", response.get_data(as_text=True)))


def test_a_practice_copy_works_on_a_chapter_problem_set(client, teacher, problem_practice):
    """"Both kinds" as an executable claim, half one. The problem routes gate on ``g.read_only``,
    so this half passes on the decorator change alone -- which is exactly why the other half
    needs its own test."""
    ws, slug = problem_practice["workspace"], problem_practice["slug"]
    client.sign_in(teacher)
    url = f"/w/{ws.public_id}/{slug}/problems/P3-01"

    submitted = client.post(url, data=RIGHT)
    # "Matches the expected entry" is the list's wording for a problem whose entry agrees with the
    # chapter's; the detail page never says it, so this is where the attempt shows.
    after_attempt = _text(client.get(f"/w/{ws.public_id}/{slug}/problems"))
    client.post(url + "/answer")
    after_reveal = _text(client.get(url))

    assert submitted.status_code == 302, f"the attempt was refused: {_text(submitted)[:400]}"
    assert "Matches the expected entry" in after_attempt, "the attempt was not recorded"
    assert "The entry this transaction calls for" in after_reveal, "the reveal did nothing"


def test_a_practice_copy_works_on_a_full_practice_set(client, session, teacher, practice, world):
    """And half two, through ``workspace_write``. These two tests failing differently is the
    signal that one gate was changed and the other was not."""
    slug = world["slug"]
    client.sign_in(teacher)
    base = f"/w/{practice.public_id}/{slug}"

    client.post(f"{base}/journals/general/entries/new", data={
        "kind": "regular", "entry_date": "2026-12-02", "document_ref": "INV-1",
        "client_key": "through-the-routes", "workspace_version": "0",
        "line-1-account": "112", "line-1-party": "C-ONE", "line-1-debit": "1,200.00",
        "line-2-account": "401", "line-2-credit": "1,200.00",
    })
    recorded = _entries(session, practice)
    client.post(f"{base}/journals/general/post")
    posted = active_posted_entry_ids(session, practice, "general")
    client.post(f"{base}/submit")

    assert recorded == 1, "the entry route recorded nothing"
    assert posted, "the posting route posted nothing"
    session.refresh(practice)
    assert practice.status == "submitted", "the submit route did not hand the copy in"


def test_the_problem_set_fence_still_applies_to_a_practice_copy(
    client, teacher, problem_practice, practice, world
):
    """The two features meet here. ``decorators._fence`` keys on the pack's kind, not on who owns
    the workspace, so a teacher practising a chapter must still get 404 on journals, ledgers,
    statements, the trial balance, checkpoints and the print record -- and the problem routes must
    still 404 on their practice copy of a practice set."""
    client.sign_in(teacher)
    chapter = f"/w/{problem_practice['workspace'].public_id}/{problem_practice['slug']}"
    practice_set = f"/w/{practice.public_id}/{world['slug']}"

    fenced = {
        path: client.get(f"{chapter}{path}").status_code
        for path in ("/journals", "/ledgers/general", "/statements", "/trial-balance",
                     "/checkpoints", "/print", "/documents")
    }
    fenced["problems, in a practice set"] = client.get(f"{practice_set}/problems").status_code

    assert all(status == 404 for status in fenced.values()), \
        f"the fence let something through: {sorted(k for k, v in fenced.items() if v != 404)}"
