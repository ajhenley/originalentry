"""The screens a teacher actually touches, and the copy only its owner can see.

Three claims, and each one fails silently without a test of its own:

* **Owner-only holds at the lookup, not at the layout.** ``staff/views._workspace_or_404`` scopes
  by assignment and section and feeds seven console routes. A co-teacher or an admin holding a
  practice copy's ``public_id`` reached all seven through it, and ``decorators.workspace_view``
  could not have stopped them -- it is not on those routes. The spec is explicit: a practice copy
  is visible to its owner alone. ``abort(404)``, never 403, so a probe cannot confirm it exists.
* **The banner is standing, not conditional.** A live practice copy is writable, so
  ``g.read_only`` is False and the one notice slot in ``layouts/workspace.html`` was empty. The
  anti-goal is a teacher mistaking their own copy for a student's -- they are the only person who
  can see it, and they are told every time they look.
* **The console says which action it is about to take.** "Work this myself" and "start over" are
  different buttons with different consequences, and an assignment with a live copy has to say so
  rather than silently resuming: a set takes hours, and silently resuming is how an afternoon of
  work looks lost.

And one that holds two things at once: the progress screen offers the action while the progress
table still excludes the copy from the class's rows. Both, on one screen.

Every fixture creates everything it later asserts on. The suite runs against a shared development
branch that holds rows from earlier manual testing, so a fixture leaning on the database being
empty -- or on a row it did not create -- would be accidentally sighted rather than blind.
"""

from __future__ import annotations

import ast
import html
import inspect
import re
import textwrap
from datetime import UTC, datetime

import pytest
from originalentry import messages
from originalentry.models import (
    ROLE_ADMIN,
    ROLE_INSTRUCTOR,
    AuditLog,
    ContentPack,
    PackVersion,
    Section,
    SectionStaff,
    User,
    Variant,
    Workspace,
)
from originalentry.packs import schema
from originalentry.packs.importer import import_answer_keys, import_content
from originalentry.services import practice
from originalentry.services.assignments import MANUAL, create_assignment
from originalentry.services.practice import PracticeOwnerNotStaff, open_practice, practice_copy
from originalentry.services.progress import assignment_progress
from originalentry.staff import views
from originalentry.staff.views import (
    PRACTICE_ACCEPTED_AT_THE_CONSOLE,
    PRACTICE_REFUSED_AT_THE_CONSOLE,
)
from sqlalchemy import select

from tests.packs import testco_alpha

pytestmark = pytest.mark.db


# ── the world ──────────────────────────────────────────────────────────────────────────

def _user(email: str, *, role: str | None = None, family_name: str = "Sowande") -> User:
    user = User(email=email, given_name="Ada", family_name=family_name)
    if role is not None:
        user.role = role
    return user


@pytest.fixture
def world(session):
    """One assignment, one student's books, and the four accounts that ask about them.

    The co-teacher and the admin are the two people the spec names as *not* allowed to see a
    practice copy, and the outsider is the one ``open_practice`` itself would admit: it applies no
    section-staff check, only a role check, so an instructor who teaches a different section could
    open a copy on this assignment if the route let them. Each of the three is a real account with
    real section rows, because a 404 for somebody who does not exist proves nothing.

    No practice copy yet: the console has to be asked about an assignment that has none, and the
    tests that need one build it through ``open_practice`` so they are asserting on the shape the
    service really makes.
    """
    pack_version = import_content(session, schema.load_pack(testco_alpha.PACK),
                                  source_sha256="scrn" + "0" * 60)
    import_answer_keys(session, pack_version,
                       {"A": schema.load_answer_key(testco_alpha.KEY_A)})
    variant_id = session.scalars(
        select(Variant.id).where(Variant.pack_version_id == pack_version.id)).first()

    section = Section(name="Sec", join_code="screens-join")
    other_section = Section(name="Somebody else's", join_code="screens-other")
    teacher = _user("screens-teacher@example.edu", role=ROLE_INSTRUCTOR,
                    family_name="Teacherson")
    co_teacher = _user("screens-co-teacher@example.edu", role=ROLE_INSTRUCTOR,
                       family_name="Cotelli")
    admin = _user("screens-admin@example.edu", role=ROLE_ADMIN, family_name="Adminson")
    outsider = _user("screens-outsider@example.edu", role=ROLE_INSTRUCTOR,
                     family_name="Outerbridge")
    student = _user("screens-student@example.edu", family_name="Studentson")
    session.add_all([section, other_section, teacher, co_teacher, admin, outsider, student])
    session.flush()
    session.add_all([
        SectionStaff(section_id=section.id, user_id=teacher.id),
        SectionStaff(section_id=section.id, user_id=co_teacher.id),
        SectionStaff(section_id=other_section.id, user_id=outsider.id),
    ])
    assignment = create_assignment(session, section=section, title="December",
                                   pack_version=pack_version)
    student_workspace = Workspace(assignment_id=assignment.id, student_id=student.id,
                                  pack_version_id=pack_version.id, variant_id=variant_id,
                                  status="in_progress")
    session.add(student_workspace)
    session.flush()
    # **Committed, not merely flushed.** Several of the routes walked below roll the session back
    # before flashing a refusal -- ``progress_variant`` and this task's own two actions all do,
    # because ``app._register_audit`` commits on the way out of every staff request and a refusal
    # that left work pending would be committed with it. ``tests/conftest.py`` binds the Session
    # with ``join_transaction_mode="create_savepoint"``, so this commit releases a SAVEPOINT
    # inside the still-open outer transaction: the rows survive a view's rollback and the teardown
    # rollback still removes them. Flushed only, the first refusal in a walk takes the whole world
    # with it -- including the signed-in user, after which every later request redirects to
    # sign-in with a 302 that a "not 404" assertion reads as success.
    session.commit()
    version = session.get(PackVersion, pack_version.id)
    return {
        "section": section, "assignment": assignment, "teacher": teacher,
        "co_teacher": co_teacher, "admin": admin, "outsider": outsider, "student": student,
        "student_workspace": student_workspace, "pack_version": pack_version,
        "slug": session.get(ContentPack, version.content_pack_id).slug,
    }


@pytest.fixture
def copy(session, world):
    """The teacher's live practice copy, made the way the service makes one."""
    made = open_practice(session, world["assignment"], world["teacher"])
    session.commit()
    return made


@pytest.fixture
def manual_assignment(session, world):
    """An assignment that hands variants out by hand, which cannot be practised.

    ``services.practice`` refuses it with a reason a screen can print, because the only hand-out
    screen excludes practice copies: the copy would exist, refuse every write, and have nothing
    on screen to fix it.
    """
    made = create_assignment(session, section=world["section"], title="By hand",
                             pack_version=world["pack_version"], variant_policy=MANUAL)
    session.commit()
    return made


# ── helpers ────────────────────────────────────────────────────────────────────────────

def _text(response) -> str:
    """The visible text, so an assertion is about the page and not about its markup.

    Entities are unescaped as well as tags stripped. Jinja autoescaping turns the apostrophe in
    "the class's figures" into ``&#39;``, so a comparison against the string in ``messages`` fails
    on a page that is in fact word-for-word right -- and the obvious repair, rewriting the
    sentence to dodge the apostrophe, would be letting the test choose the prose.
    """
    return html.unescape(
        re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", response.get_data(as_text=True))))


def _console_requests(assignment: str, workspace: str) -> list[tuple[str, str, dict]]:
    """Every console route that reaches a workspace through ``_workspace_or_404``.

    Ordered so the one that *changes* the workspace comes last: ``archive`` opens a fresh set and
    archives this one, after which every later route in the same walk would 404 for a reason that
    is not scoping. The admission walk below depends on that order; the refusal walks do not, and
    are unaffected either way.
    """
    grading = f"/staff/grading/{assignment}/{workspace}"
    progress = f"/staff/progress/{assignment}"
    return [
        ("GET", grading, {}),
        ("POST", f"{progress}/variant", {"workspace": workspace, "variant": "A"}),
        ("POST", f"{progress}/accommodation",
         {"workspace": workspace, "due_at": "2027-01-04T12:00", "reason": "Illness"}),
        ("POST", f"{grading}/override",
         {"component_key": "journal_entries", "points": "8", "reason": "By hand"}),
        ("POST", f"{grading}/comment", {"body": "A word about the trial balance"}),
        ("POST", f"{grading}/reopen", {"reason": "Handed in by mistake"}),
        ("POST", f"{grading}/archive", {"reason": "Started in the wrong company"}),
    ]


def _walk_console(client, assignment: str, workspace: str) -> dict[str, int]:
    return {where: code for where, code, _ in _walk_console_fully(client, assignment, workspace)}


def _walk_console_fully(client, assignment: str, workspace: str) -> list[tuple[str, int, str]]:
    """Each route walked, with where its answer points: (request, status, Location).

    The Location matters in the admission direction. A route that rolls the session back takes
    the signed-in user's row with it if the fixture only flushed, and every later request in the
    walk then redirects to sign-in -- a 302 that "not 404" reads as the route having been entered.
    """
    walked = []
    for method, path, data in _console_requests(assignment, workspace):
        response = client.open(path, method=method, data=data)
        walked.append((f"{method} {path}", response.status_code,
                       response.headers.get("Location", "")))
    return walked


#: The workspace pages a practice set has. Walked whole rather than sampled: the banner lives in
#: the shared chrome, so a page that extended a different layout would be the one that loses it,
#: and that page is exactly the one nobody thought to sample. ``/print`` is that page -- it
#: renders ``print/workspace.html`` straight off ``base.html``, with no workspace chrome at all --
#: and it is also the page where a silent practice copy does the most harm, because a printed
#: record with nothing on it to say so is precisely a teacher's attempts read as a student's.
WORKSPACE_PAGES = ("/", "/how-to", "/documents", "/journals", "/journals/general",
                   "/trial-balance", "/ledgers/general", "/statements", "/checkpoints",
                   "/reference", "/submit", "/marks", "/print")


def _pages_of(client, workspace: str, slug: str) -> dict[str, tuple[int, str]]:
    """Every workspace page, as ``{path: (status, visible text)}``.

    The status is returned and asserted on rather than inferred from the body. Flask's 404 page
    has a non-empty body, so a test that only looks for the *absence* of a string passes on a wall
    of 404s -- which is the shape ``test_a_students_workspace_carries_no_such_banner`` was in, and
    the shape the inside-out guard on it could not detect.
    """
    pages = {}
    for page in WORKSPACE_PAGES:
        response = client.get(f"/w/{workspace}/{slug}{page}")
        pages[page] = (response.status_code, _text(response))
    return pages


def _other_than(pages: dict[str, tuple[int, str]], wanted: int) -> list[str]:
    return sorted(f"{page} -> {code}" for page, (code, _) in pages.items() if code != wanted)


def _saying_it_is_a_practice_copy(pages: dict[str, tuple[int, str]]) -> list[str]:
    return sorted(page for page, (_, body) in pages.items()
                  if messages.OWN_PRACTICE_COPY in body)


# ── owner-only, at the lookup ──────────────────────────────────────────────────────────

def _reaches_nothing(client, world, copy, who: str) -> list[str]:
    """Both surfaces, for one persona who must see nothing of this copy.

    **Two surfaces, and they need separate checks.** The seven console routes reach a workspace
    through ``staff/views._workspace_or_404``; the thirteen workspace screens reach it through
    ``decorators.workspace_view``, whose only ownership gate is ``is_owner or is_staff`` -- and
    ``is_staff`` is True for a colleague who teaches the section and for every admin. Walking only
    the console, which is what these two tests used to do, left the `/w/` screens open: either of
    them could read every page of somebody else's practice copy, with ``g.read_only_message``
    naming its owner. That is the project's first anti-goal, on the very pages this task gives a
    banner to.
    """
    client.sign_in(world[who])
    reached = [f"{where} -> {code}" for where, code in
               _walk_console(client, world["assignment"].public_id, copy.public_id).items()
               if code != 404]
    return reached + _other_than(_pages_of(client, copy.public_id, world["slug"]), 404)


def test_a_co_teacher_cannot_reach_a_colleagues_practice_copy(client, session, world, copy):
    """_workspace_or_404 scopes by assignment and section only, and feeds seven console routes;
    workspace_view admits anybody who teaches the section. Neither is owner-only on its own. 404,
    never 403."""
    reached = _reaches_nothing(client, world, copy, "co_teacher")

    assert not reached, "a co-teacher reached a colleague's practice copy:\n  " + "\n  ".join(
        reached)


def test_an_admin_cannot_reach_a_teachers_practice_copy(client, session, world, copy):
    """Stricter than the existing rule, and deliberately: an admin sees every section's books, and
    the point of a practice copy is somewhere unobserved."""
    reached = _reaches_nothing(client, world, copy, "admin")

    assert not reached, "an admin reached a teacher's practice copy:\n  " + "\n  ".join(reached)


def test_the_owner_is_refused_the_console_actions_too(client, session, world, copy):
    """Per-route, and the decision is the same at all seven: an action whose purpose is one person
    marking, archiving or extending another's work has no meaning where both are the same person,
    and offering it is worse than refusing it. The owner's way in is the student screens, and the
    way back to a writable copy is start over."""
    client.sign_in(world["teacher"])

    reached = {r: code for r, code in
               _walk_console(client, world["assignment"].public_id, copy.public_id).items()
               if code != 404}

    assert not reached, "the console offered an action a practice copy has no meaning for:\n  " \
        + "\n  ".join(f"{r} -> {code}" for r, code in sorted(reached.items()))


def test_the_same_routes_still_reach_a_students_workspace(client, session, world):
    """The refusal walks from the inside: refusing everybody everywhere would pass all three.

    Any status but 404 means the route was entered, which is all this asserts -- several of these
    then refuse on their own terms (no variant to hand out, nothing to give back) and flash it.
    """
    client.sign_in(world["teacher"])

    walked = _walk_console_fully(client, world["assignment"].public_id,
                                 world["student_workspace"].public_id)

    refused = sorted(f"{where} -> {code}" for where, code, _ in walked if code == 404)
    adrift = sorted(f"{where} -> {where_to}" for where, _, where_to in walked
                    if "sign-in" in where_to)
    assert not adrift, "these never reached the route at all:\n  " + "\n  ".join(adrift)
    assert not refused, "stopped reaching a student's workspace:\n  " + "\n  ".join(refused)


def test_the_owner_can_reach_their_own_through_the_student_screens(client, session, world, copy):
    """Which is the whole point of the refusals above: the copy is worked, not marked.

    The other half of owner-only, and the half that breaks teaching rather than privacy: a check
    that refused everybody would pass both persona tests clean on every route and every page.
    All thirteen, because the refusal is one line in the shared decorator and a mistake in it
    takes the whole workspace with it.
    """
    client.sign_in(world["teacher"])

    refused = _other_than(_pages_of(client, copy.public_id, world["slug"]), 200)

    assert not refused, "the owner was refused their own copy:\n  " + "\n  ".join(refused)


def test_a_teacher_removed_from_the_section_keeps_their_practice_copy(
        client, session, world, copy):
    """Reaching it needs ownership, not may_see_section. A teacher taken off the section mid-term
    still owns the hours they put into their own copy."""
    for row in session.scalars(
            select(SectionStaff).where(SectionStaff.user_id == world["teacher"].id)):
        session.delete(row)
    session.flush()
    client.sign_in(world["teacher"])

    opened = client.get(f"/w/{copy.public_id}/{world['slug']}/")

    assert opened.status_code == 200, "a teacher lost their own copy with their section"
    assert messages.OWN_PRACTICE_COPY in _text(opened)
    assert not _other_than(_pages_of(client, copy.public_id, world["slug"]), 200), \
        "ownership stopped carrying the copy once the section staffing went"


def test_a_student_cannot_reach_a_teachers_practice_copy(client, session, world, copy):
    client.sign_in(world["student"])

    assert client.get(f"/w/{copy.public_id}/{world['slug']}/").status_code == 404


def _called_name(func: ast.AST) -> str | None:
    """The bare name a call is written with: ``f(...)`` and ``mod.f(...)`` both answer ``f``."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _calls(source, name: str) -> bool:
    """Whether this function really **calls** ``name``, read off its syntax tree.

    Not ``name + "(" in inspect.getsource(...)``, which is what this and the handler scan below
    were written as, and which a docstring can flip. ``staff.practice_grade``'s docstring explains
    at length why it does *not* go through ``_workspace_or_404`` -- and under a substring check,
    writing that function's name with its parentheses anywhere in that prose put the route into
    the set below and printed "routes reaching a workspace with no declared decision:
    staff.practice_grade". A loud wrong diagnosis is worse than a silent one in a guard whose
    whole value is being auditable: it is false about the code, and it sends the next person
    hunting a call that does not exist.

    The question was always structural -- *does this view reach a workspace through that lookup?*
    -- so it is asked of the tree, where prose cannot be mistaken for code. The same lesson the
    chokepoint guard spent four rounds learning in ``tests/guards/test_practice_chokepoint.py``.
    """
    text = source if isinstance(source, str) else inspect.getsource(source)
    return any(isinstance(node, ast.Call) and _called_name(node.func) == name
               for node in ast.walk(ast.parse(textwrap.dedent(text))))


def test_the_scan_sees_a_call_and_not_a_docstring():
    """Both directions of the scan above, on stubs, because the guard it feeds cannot show them.

    With the real routes it can only ever say "the set came out right", which is equally true of
    a scan that reads prose as code -- that is exactly the state this was in. In the idiom of
    ``test_practice_chokepoint``'s would-catch-a-real-one / does-not-cry-wolf pair.
    """
    def calls_it():
        return _workspace_or_404(None, "")                      # noqa: F821

    def only_talks_about_it():
        """Not through ``_workspace_or_404(found, id)``, and here is the paragraph saying why."""
        return None

    assert _calls(calls_it, "_workspace_or_404")
    assert not _calls(only_talks_about_it, "_workspace_or_404")


def test_every_route_reaching_a_workspace_through_the_scoped_lookup_declares_its_decision(app):
    """The decision is a literal mapping, so it is auditable rather than scattered through seven
    route bodies -- and a route added next year has to make the decision rather than inherit one.

    Source inspection, in the idiom of this repo's other guards: what matters is which routes
    reach a workspace through the scoped lookup, and no amount of calling six of them says
    anything about the seventh.

    **What the name claims, exactly.** The set is the routes that reach a workspace through
    ``_workspace_or_404`` -- the lookup whose scope is assignment and section, which is the right
    scope for a student's books and the wrong one for a teacher's own, and which is therefore the
    one place the owner-only rule and the per-route decision can live. It is **not** every route
    that touches a workspace, and the three practice actions are the proof: ``practice_open`` and
    ``practice_restart`` reach one through ``services.practice``, ``practice_grade`` through
    ``practice_copy``, and each of the three is pinned to the signed-in caller and takes no
    workspace id from the request at all. They have nothing to declare because they cannot reach
    anybody else's copy -- the mapping's question, *does this action mean anything when the owner
    is the one clicking*, is answered by those routes existing.

    So this guard does not see a route that reaches a workspace by an id from the request without
    going through the lookup. Nothing in the tree does that today, and such a route would be a
    second copy of the scoping rule, which is what the lookup exists to prevent -- but the gap is
    real and is said here rather than left for the name to paper over.
    """
    declared = set(PRACTICE_REFUSED_AT_THE_CONSOLE) | set(PRACTICE_ACCEPTED_AT_THE_CONSOLE)
    overlap = set(PRACTICE_REFUSED_AT_THE_CONSOLE) & set(PRACTICE_ACCEPTED_AT_THE_CONSOLE)

    reached = set()
    for rule in app.url_map.iter_rules():
        view = app.view_functions.get(rule.endpoint)
        if view is None or not rule.rule.startswith("/staff/"):
            continue
        if _calls(view, "_workspace_or_404"):
            reached.add(rule.endpoint)

    assert not overlap, f"endpoints both refused and accepted: {sorted(overlap)}"
    assert reached == declared, (
        f"routes reaching a workspace with no declared decision: {sorted(reached - declared)}; "
        f"declared but reaching no workspace: {sorted(declared - reached)}"
    )


def test_every_declared_endpoint_is_a_real_route(app):
    """A decision recorded against a renamed endpoint decides nothing and reads like cover."""
    known = {rule.endpoint for rule in app.url_map.iter_rules()}
    declared = set(PRACTICE_REFUSED_AT_THE_CONSOLE) | set(PRACTICE_ACCEPTED_AT_THE_CONSOLE)

    assert not declared - known, f"decisions naming no route: {sorted(declared - known)}"


# ── the standing banner ────────────────────────────────────────────────────────────────

def test_every_page_of_a_practice_copy_says_what_it_is(client, session, world, copy):
    """The anti-goal is a teacher mistaking it for a student's. They are the only person who can
    see it and they are told every time they look -- on a live copy, which is writable, so the
    read-only slot alone could never have carried it."""
    client.sign_in(world["teacher"])

    pages = _pages_of(client, copy.public_id, world["slug"])

    silent = sorted(set(pages) - set(_saying_it_is_a_practice_copy(pages)))
    assert not _other_than(pages, 200), "a page did not open, so it says nothing either way"
    assert not silent, "pages of a practice copy that do not say so: " + ", ".join(silent)


def test_a_students_workspace_carries_no_such_banner(client, session, world):
    """Said on a student's own screen and on a teacher's view of it: the banner is about the one
    workspace that is a practice copy, not about who is looking."""
    client.sign_in(world["student"])
    student_sees = _pages_of(client, world["student_workspace"].public_id, world["slug"])
    client.sign_in(world["teacher"])
    teacher_sees = _pages_of(client, world["student_workspace"].public_id, world["slug"])

    said = sorted(set(_saying_it_is_a_practice_copy(student_sees))
                  | set(_saying_it_is_a_practice_copy(teacher_sees)))
    # Asserted before the absence, and on the status rather than on a non-empty body: Flask's 404
    # page is non-empty, so a wall of 404s would satisfy "the banner is absent" and satisfy an
    # inside-out guard that only asked whether something was rendered.
    assert not _other_than(student_sees, 200), "the student could not open their own workspace"
    assert not _other_than(teacher_sees, 200), "the teacher could not read the student's books"
    assert not said, "a student's workspace claimed to be a practice copy: " + ", ".join(said)


def test_an_archived_practice_copy_says_when_it_was_archived(client, session, world, copy):
    """``is_staff and not is_owner`` is False for a practice copy, so an archived one fell through
    to the submitted/else chain and the banner slot rendered ``None``: read-only, with no reason
    given and no date. Start over is what first makes an archived practice copy reachable."""
    copy.archived_at = datetime(2026, 10, 3, 9, 0, tzinfo=UTC)
    session.flush()
    client.sign_in(world["teacher"])

    body = _text(client.get(f"/w/{copy.public_id}/{world['slug']}/"))

    assert messages.OWN_PRACTICE_COPY in body, "the standing banner went with the archiving"
    assert "Archived on 3 Oct 2026" in body, f"no archived-on date in the banner: {body[:400]}"
    assert "None" not in body.split("Archived on")[0][-120:]


# ── the console ────────────────────────────────────────────────────────────────────────

def _progress(client, world) -> str:
    response = client.get(f"/staff/progress/{world['assignment'].public_id}")
    assert response.status_code == 200, "the progress screen did not open"
    return _text(response)


def test_the_progress_screen_offers_work_this_myself(client, session, world):
    client.sign_in(world["teacher"])

    body = _progress(client, world)

    assert "Work this assignment myself" in body
    assert "Start over" not in body, "start over, with no copy to start over from"


def test_the_action_says_resume_once_a_copy_exists(client, session, world, copy):
    """Silently resuming is how an hour of work looks lost."""
    client.sign_in(world["teacher"])

    body = _progress(client, world)

    assert "You have your own copy of this assignment open" in body
    assert "Resume your copy" in body
    assert "Work this assignment myself" not in body, "the console offers to open a second copy"


def test_start_over_is_a_separate_action(client, session, world, copy):
    client.sign_in(world["teacher"])
    response = client.get(f"/staff/progress/{world['assignment'].public_id}")
    body = response.get_data(as_text=True)
    assignment = world["assignment"].public_id

    assert f"/staff/progress/{assignment}/practice/restart" in body
    assert f'action="/staff/progress/{assignment}/practice"' in body, \
        "resume and start over post to the same place"
    assert "Start over" in _text(response)


def test_a_colleague_is_offered_nothing_about_this_teachers_copy(client, session, world, copy):
    """The console is per-viewer: a co-teacher's own practice copy is a different row, and this
    screen must not tell them that somebody else holds one."""
    client.sign_in(world["co_teacher"])

    body = _progress(client, world)

    assert "You have your own copy of this assignment open" not in body
    assert "Work this assignment myself" in body, "a co-teacher may practise it too"


def test_opening_from_the_console_lands_in_the_copy(client, session, world):
    client.sign_in(world["teacher"])
    assignment = world["assignment"].public_id

    opened = client.post(f"/staff/progress/{assignment}/practice")

    made = practice_copy(session, world["assignment"], world["teacher"])
    assert made is not None, "the action created nothing"
    assert opened.status_code == 302
    assert opened.headers["Location"] == f"/w/{made.public_id}/{world['slug']}/"


def test_resuming_returns_the_same_copy_rather_than_a_second_one(client, session, world, copy):
    client.sign_in(world["teacher"])
    assignment = world["assignment"].public_id

    resumed = client.post(f"/staff/progress/{assignment}/practice")

    live = session.scalars(
        select(Workspace).where(Workspace.assignment_id == world["assignment"].id,
                                Workspace.student_id == world["teacher"].id,
                                Workspace.archived_at.is_(None))).all()
    assert resumed.headers["Location"] == f"/w/{copy.public_id}/{world['slug']}/"
    assert [ws.id for ws in live] == [copy.id], "resuming opened a second copy"


def test_starting_over_archives_the_old_copy_and_opens_a_fresh_one(client, session, world, copy):
    client.sign_in(world["teacher"])
    assignment = world["assignment"].public_id

    restarted = client.post(f"/staff/progress/{assignment}/practice/restart")

    session.refresh(copy)
    fresh = practice_copy(session, world["assignment"], world["teacher"])
    assert copy.archived_at is not None, "the old copy was not archived"
    assert fresh is not None and fresh.id != copy.id
    assert fresh.staff_practice is True, "start over handed back an ordinary workspace"
    assert restarted.headers["Location"] == f"/w/{fresh.public_id}/{world['slug']}/"


def test_a_refused_open_shows_the_reason(client, session, world, manual_assignment):
    """PracticeRefused's reason reaches the screen rather than a 500."""
    client.sign_in(world["teacher"])

    refused = client.post(f"/staff/progress/{manual_assignment.public_id}/practice",
                          follow_redirects=True)

    assert refused.status_code == 200
    assert practice.MANUAL_VARIANT in _text(refused)
    assert practice_copy(session, manual_assignment, world["teacher"]) is None


def test_a_refused_start_over_shows_the_reason_too(client, session, world, manual_assignment):
    client.sign_in(world["teacher"])

    refused = client.post(f"/staff/progress/{manual_assignment.public_id}/practice/restart",
                          follow_redirects=True)

    assert practice.MANUAL_VARIANT in _text(refused)


def test_an_owner_who_is_not_staff_is_a_404_and_not_a_flash(
        client, session, world, monkeypatch):
    """``PracticeOwnerNotStaff`` is a sibling of ``PracticeRefused``, not a subclass, and carries
    no printable reason: it means the sole writer of a deadline-bypassing flag was asked to set it
    for an account that is not staff. A route that flashed it would say something a teacher cannot
    tell from "this assignment is student-choice", and nothing would ever notice. The house answer
    is 404.

    Raised from a stub rather than reached through the route, because ``@staff_view`` refuses a
    non-staff caller first -- which is the belt, and this is the braces.
    """
    def _breach(*args, **kwargs):
        raise PracticeOwnerNotStaff(practice.STAFF_ONLY)

    monkeypatch.setattr("originalentry.staff.views.open_practice", _breach)
    monkeypatch.setattr("originalentry.staff.views.restart_practice", _breach)
    client.sign_in(world["teacher"])
    assignment = world["assignment"].public_id

    opened = client.post(f"/staff/progress/{assignment}/practice")
    restarted = client.post(f"/staff/progress/{assignment}/practice/restart")

    assert (opened.status_code, restarted.status_code) == (404, 404)


def _handlers_of(source: str) -> list[tuple[set[str], set[str]]]:
    """Every ``except`` clause in this source, as (classes caught, functions called)."""
    found = []
    for node in ast.walk(ast.parse(textwrap.dedent(source))):
        if not isinstance(node, ast.ExceptHandler):
            continue
        caught = {name.id for name in ast.walk(node.type or ast.Pass())
                  if isinstance(name, ast.Name)}
        called = {call.func.id for call in ast.walk(node)
                  if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)}
        found.append((caught, called))
    return found


def test_the_two_refusals_are_not_handled_alike(app):
    """The defect the split exists to prevent, read off the syntax tree.

    ``PracticeRefused`` carries a printable reason and is flashed. ``PracticeOwnerNotStaff`` is a
    sibling class, not a subclass, carries no reason, and means the sole writer of a
    deadline-bypassing flag was asked to set it for an account that is not staff. A clause that
    caught both -- or caught ``Exception`` -- would print the second as a sentence a teacher
    cannot tell from "this assignment is student-choice", and nothing would ever notice. Asserting
    on the two status codes alone cannot see that: 404 and a flashed 302 look right either way
    while the *distinction* has quietly been written as one clause.
    """
    where = {endpoint: app.view_functions[endpoint] for endpoint in
             ("staff.practice_open", "staff.practice_restart")}
    handlers = _handlers_of(inspect.getsource(views._into_my_practice_copy))
    for view in where.values():
        handlers.extend(_handlers_of(inspect.getsource(view)))

    offenders = []
    for endpoint, view in where.items():
        if not _calls(view, "_into_my_practice_copy"):
            offenders.append(f"{endpoint} does not go through the one handler")
    for caught, called in handlers:
        if "Exception" in caught:
            offenders.append("a clause catches Exception, which swallows the breach")
        if {"PracticeRefused", "PracticeOwnerNotStaff"} <= caught:
            offenders.append("one clause catches both, which is the defect this split prevents")
        if caught == {"PracticeRefused"} and ("flash" not in called or "abort" in called):
            offenders.append(f"the printable refusal is not flashed: {sorted(called)}")
        if caught == {"PracticeOwnerNotStaff"} and ("abort" not in called or "flash" in called):
            offenders.append(f"the breach does not reach abort(404) alone: {sorted(called)}")

    kinds = {frozenset(caught) for caught, _ in handlers}
    assert frozenset({"PracticeRefused"}) in kinds, "nothing catches PracticeRefused: a reason 500s"
    assert frozenset({"PracticeOwnerNotStaff"}) in kinds, "nothing turns the breach into a 404"
    assert not offenders, "; ".join(sorted(set(offenders)))


# ── scoping, which is all that stands between a foreign teacher and this assignment ────

def test_a_foreign_teacher_cannot_open_a_practice_copy_here(client, session, world):
    """``open_practice`` applies no section-staff check -- it checks role only -- so an instructor
    who teaches a different section would be admitted by the service. The whole of the refusal
    rests on the route's scoping."""
    client.sign_in(world["outsider"])
    assignment = world["assignment"].public_id

    opened = client.post(f"/staff/progress/{assignment}/practice")
    restarted = client.post(f"/staff/progress/{assignment}/practice/restart")

    assert (opened.status_code, restarted.status_code) == (404, 404)
    assert practice_copy(session, world["assignment"], world["outsider"]) is None


def test_a_student_cannot_open_a_practice_copy(client, session, world):
    client.sign_in(world["student"])
    assignment = world["assignment"].public_id

    assert client.post(f"/staff/progress/{assignment}/practice").status_code == 404
    assert client.post(f"/staff/progress/{assignment}/practice/restart").status_code == 404


def test_the_action_is_not_offered_on_an_archived_assignment(client, session, world):
    """A reviewer ruled that ``services/practice.py`` must not check ``assignment.archived_at``:
    ``open_workspace`` does not either, and filtering archived assignments is a listing concern
    everywhere in this codebase. That obligation lands on the route, which reaches its subject
    through ``_assignment_or_404`` -- and that lookup pins ``archived_at=None``, so the screen
    that would offer the action cannot be opened either.
    """
    world["assignment"].archived_at = datetime(2026, 9, 1, tzinfo=UTC)
    session.flush()
    client.sign_in(world["teacher"])
    assignment = world["assignment"].public_id

    screen = client.get(f"/staff/progress/{assignment}")
    opened = client.post(f"/staff/progress/{assignment}/practice")
    restarted = client.post(f"/staff/progress/{assignment}/practice/restart")

    assert (screen.status_code, opened.status_code, restarted.status_code) == (404, 404, 404)


# ── both, on one screen ────────────────────────────────────────────────────────────────

def test_the_progress_table_still_does_not_list_the_copy(client, session, world, copy):
    """The console offers the action and excludes the row: both, on one screen."""
    client.sign_in(world["teacher"])
    response = client.get(f"/staff/progress/{world['assignment'].public_id}")
    body = response.get_data(as_text=True)

    assert world["student_workspace"].public_id in body, "the table lost the student"
    assert copy.public_id not in body, "the practice copy is in the class's rows"
    assert "Resume your copy" in _text(response), "the action went with the row"


def test_the_table_still_lists_the_student_it_should(session, world, copy):
    """Guards the test above from the inside: a progress table that listed nobody would pass it."""
    rows = [row.student_email for row in assignment_progress(session, world["assignment"])]

    assert rows == [world["student"].email]


# ── the durable trail ──────────────────────────────────────────────────────────────────
#
# ``services.audit.should_audit`` is a pure decision with its own unit tests, and this is the half
# those cannot see: that the request hook actually asks it about the workspace in hand. Change
# ``should_audit`` alone and every one of those unit tests still passes while a teacher's practice
# afternoon is still one never-purged, admin-visible AuditLog row per request, each one labelled
# ``student.*``. So the claim is made here, against a real request to a real practice copy.


def _durable_trail(session, actor) -> list[str]:
    """The durable AuditLog actions recorded against one account, oldest first.

    Filtered to one account this test created, because the suite runs against a shared development
    branch and audit_log is the one table nothing purges -- rows from earlier manual testing are
    certainly in it.
    """
    return list(session.scalars(
        select(AuditLog.action).where(AuditLog.actor_id == actor.id).order_by(AuditLog.id)))


def test_a_page_of_a_practice_copy_leaves_no_row_in_the_durable_trail(
    client, session, world, copy
):
    """A teacher working their own copy is workspace traffic, which audit.py keeps out of the
    durable trail on purpose: the row would be durable, identifying, never purged, visible to
    every admin in ``staff.activity`` and its CSV export, and it would say the copy exists.

    The console request is the control, and it goes **first**. Without a control, a hook that had
    stopped recording altogether -- or one swallowing an exception, which it does by design --
    would read as the carve-out working. And it has to be first because ``tests/conftest.py``
    holds one app context open for the whole test and Flask reuses it per request, so ``g`` is not
    cleared between the requests of one test the way it is in production (where every request
    pushes its own app context). With the practice page first, its ``g.workspace`` would still be
    set during the console request and the control would be suppressed by the test harness rather
    than by the code under test.
    """
    client.sign_in(world["teacher"])
    assert _durable_trail(session, world["teacher"]) == [], "the fixture recorded a row already"

    console = client.get(f"/staff/progress/{world['assignment'].public_id}")
    page = client.get(f"/w/{copy.public_id}/{world['slug']}/")

    assert (page.status_code, console.status_code) == (200, 200), "a request did not land"
    trail = _durable_trail(session, world["teacher"])
    assert not [action for action in trail if action.startswith("student.")], \
        f"the teacher's own practice traffic is in the durable trail: {trail}"
    assert [action for action in trail if action.startswith("staff.")], \
        f"the hook recorded nothing at all, so the absence above proves nothing: {trail}"


def test_a_students_books_are_still_recorded_when_staff_read_them(client, session, world):
    """The other direction, and the one that matters if the carve-out over-matches: a teacher
    reading a *student's* books is a privileged read of somebody else's record, which is exactly
    what the durable trail exists for. Same blueprint, same endpoint, same role as the test above.
    """
    client.sign_in(world["teacher"])

    page = client.get(f"/w/{world['student_workspace'].public_id}/{world['slug']}/")

    assert page.status_code == 200, "the teacher could not read the student's books"
    trail = _durable_trail(session, world["teacher"])
    assert [action for action in trail if action.startswith("student.")], \
        f"a staff read of a student's workspace left no durable record: {trail}"


def test_the_request_hook_reads_the_decision_rather_than_re_deriving_it():
    """The hook must read ``g.own_practice``, not call ``is_own_practice`` a second time.

    Both answer the same question -- ``decorators.workspace_view`` sets ``g.workspace`` two
    statements above ``g.own_practice``, after every abort -- so this is not a correctness claim.
    It is a cost claim, and the suite cannot make it any other way.

    Re-deriving reads ``workspace.staff_practice``. In production the session commits inside the
    view and ``expire_on_commit`` defaults to True, so by the time an ``after_request`` hook runs
    the row is expired and that attribute costs a refresh SELECT. The hook runs on *every*
    response, and the argument is evaluated before ``should_audit`` is entered -- so every student
    saving an entry line paid that query for the hook to learn the flag is False and then reject
    the request on role two branches later. Entry lines are the busiest write in the application.
    Reading the bool off ``g`` costs nothing and is the same answer.

    No behavioural test in this suite can see that: ``tests/conftest.py`` binds its Session with
    ``expire_on_commit=False``, so the attribute is never expired here and the SELECT never
    happens, whichever way the hook is written. That is also why it shipped. The claim is
    therefore made structurally, against the syntax tree, and the two tests above remain the
    proof that the carve-out still *works* -- this one only says what it must not cost.

    The default matters and is asserted by inspection, not here: ``getattr(g, "own_practice",
    False)`` over-records if a 500 is raised in the eighteen lines between the two assignments,
    and over-recording is the safe direction for a trail that nothing can refill.
    """
    from originalentry import app as app_module

    source = inspect.getsource(app_module._register_audit)

    assert not _calls(source, "is_own_practice"), (
        "the audit hook re-derives the practice decision instead of reading g.own_practice, "
        "which costs one refresh SELECT on every request that has a workspace -- including "
        "every student's, which should_audit rejects on role anyway"
    )
