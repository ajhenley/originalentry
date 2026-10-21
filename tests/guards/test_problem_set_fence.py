"""The fence between a problem set and a practice set.

A chapter problem set is the one place in this application where three standing commitments are
relaxed: T8.8 (a signature never reaches the student) and A8 (no answer-key value reaches a
student) are exempted, because a self-grading problem has to be able to show a student what they
misunderstood and, behind a button, the answer. A7 is **not** exempted -- see
``test_a7_still_holds_on_the_problem_screens`` below.

An exemption that is not fenced is not an exemption, it is a hole. So:

* every problem-set route 404s in a practice-set workspace, and
* every practice-set route 404s in a problem-set workspace.

Both halves are enforced in one place -- ``decorators.workspace_view``, which is the only way into
a ``/w/`` route -- and the default for a route nobody classified is "practice set only", so a route
added later cannot leak into a problem set by being forgotten.
"""

from __future__ import annotations

import pytest
from flask import url_for
from originalentry.decorators import (
    PROBLEM_SET_ENDPOINTS,
    SHARED_WORKSPACE_ENDPOINTS,
)
from originalentry.models import Assignment, Section, User, Variant, Workspace
from originalentry.packs import schema
from originalentry.packs.importer import import_answer_keys, import_content
from originalentry.problems import importing
from sqlalchemy import select

from tests.packs import testco_alpha
from tests.unit.test_chapter_file import VALID

pytestmark = pytest.mark.db

#: A real ref in each kind of pack, for the routes that take one.
PLACEHOLDERS = {"problem_set": {"ref": "P3-01", "key": "general", "kind": "customer",
                                "section": "chart", "entry_id": "1", "run_id": "1",
                                "statement_type": "trial_balance"},
                "practice_set": {"ref": "INV-1", "key": "general", "kind": "customer",
                                 "section": "chart", "entry_id": "1", "run_id": "1",
                                 "statement_type": "trial_balance"}}


def _student(session, email: str) -> User:
    user = User(email=email, given_name="Ada", family_name="Sowande")
    session.add(user)
    session.flush()
    return user


def _workspace(session, version, student, *, join_code: str, required=None) -> Workspace:
    section = Section(name="Sec", join_code=join_code)
    session.add(section)
    session.flush()
    assignment = Assignment(section_id=section.id, title="Work", company_policy="fixed",
                            fixed_pack_version_id=version.id, problems_required=required)
    session.add(assignment)
    session.flush()
    variant_id = session.scalars(
        select(Variant.id).where(Variant.pack_version_id == version.id)).first()
    ws = Workspace(assignment_id=assignment.id, student_id=student.id,
                   pack_version_id=version.id, variant_id=variant_id, status="in_progress")
    session.add(ws)
    session.flush()
    return ws


@pytest.fixture
def problem_set(session):
    version = importing.import_chapter(session, VALID)
    student = _student(session, "fence-problems@example.edu")
    return _workspace(session, version, student, join_code="fence-ps", required=2), student


@pytest.fixture
def practice_set(session):
    version = import_content(session, schema.load_pack(testco_alpha.PACK),
                             source_sha256="fen" + "0" * 61)
    import_answer_keys(session, version, {"A": schema.load_answer_key(testco_alpha.KEY_A)})
    student = _student(session, "fence-practice@example.edu")
    return _workspace(session, version, student, join_code="fence-pr"), student


def _workspace_rules(app):
    """Every rule under /w/, which is every rule that goes through workspace_view."""
    return [
        rule for rule in app.url_map.iter_rules()
        if rule.rule.startswith("/w/<workspace>/") and rule.endpoint.startswith("student.")
    ]


def _walk(app, client, workspace, kind: str, rules) -> dict[str, int]:
    seen: dict[str, int] = {}
    with app.test_request_context():
        for rule in rules:
            args = {**PLACEHOLDERS[kind], "workspace": workspace.public_id,
                    "company_slug": workspace.pack_version_id and _slug(app, workspace)}
            url = url_for(rule.endpoint, **{k: args[k] for k in rule.arguments})
            for method in sorted(rule.methods & {"GET", "POST"}):
                seen[f"{method} {rule.endpoint}"] = client.open(url, method=method).status_code
    return seen


def _slug(app, workspace):
    from originalentry.extensions import db
    from originalentry.models import ContentPack, PackVersion

    version = db.session.get(PackVersion, workspace.pack_version_id)
    return db.session.get(ContentPack, version.content_pack_id).slug


# ── the lists themselves ───────────────────────────────────────────────────────────────

def test_the_problem_set_routes_all_exist(app):
    """A name in the list matching no endpoint stops fencing anything, silently -- and the hole
    it leaves is the one the whole exemption rests on."""
    endpoints = {rule.endpoint for rule in app.url_map.iter_rules()}

    missing = sorted(PROBLEM_SET_ENDPOINTS - endpoints)
    assert not missing, f"fenced endpoints that do not exist: {missing}"


def test_the_shared_routes_all_exist(app):
    endpoints = {rule.endpoint for rule in app.url_map.iter_rules()}

    missing = sorted(SHARED_WORKSPACE_ENDPOINTS - endpoints)
    assert not missing, f"shared endpoints that do not exist: {missing}"


def test_the_two_lists_do_not_overlap():
    """A route in both would be fenced and not fenced at once; the shared list wins in the code,
    so the overlap would silently unfence a problem-set route."""
    assert not (PROBLEM_SET_ENDPOINTS & SHARED_WORKSPACE_ENDPOINTS)


def test_every_workspace_route_is_classified(app):
    """The default is "practice set only", which is the safe direction -- a new route cannot leak
    into a problem set by being forgotten. This test exists so the choice stays deliberate: a new
    route shows up here and someone has to say which it is."""
    classified = PROBLEM_SET_ENDPOINTS | SHARED_WORKSPACE_ENDPOINTS
    practice_only = sorted(
        rule.endpoint for rule in _workspace_rules(app) if rule.endpoint not in classified)

    assert practice_only == [
        "student.checkpoint_submit", "student.checkpoints", "student.disposition",
        "student.document", "student.document_image", "student.documents",
        "student.entry_create", "student.entry_new", "student.entry_void",
        "student.general_ledger", "student.journal", "student.journals",
        "student.post_entry_sub", "student.post_general", "student.post_subsidiary_all",
        "student.posting_reverse", "student.print_record", "student.statement",
        "student.statement_save", "student.statements", "student.subsidiary",
        "student.trial_balance",
    ]


# ── both directions ────────────────────────────────────────────────────────────────────

def test_every_problem_set_route_404s_in_a_practice_set_workspace(app, client, practice_set):
    """Review Focus 3. The exemption is scoped to kind == problem_set; a practice-set student must
    be unable to reach any of it, or T8.8 and A8 are simply gone."""
    workspace, student = practice_set
    client.sign_in(student)
    rules = [r for r in _workspace_rules(app) if r.endpoint in PROBLEM_SET_ENDPOINTS]
    assert rules, "no problem-set rules found: this test would prove nothing"

    seen = _walk(app, client, workspace, "practice_set", rules)

    assert seen, "the walk visited nothing"
    assert all(status == 404 for status in seen.values()), \
        f"reachable from a practice set: {sorted(k for k, v in seen.items() if v != 404)}"


def test_the_practice_set_routes_404_in_a_problem_set_workspace(app, client, problem_set):
    """The other direction: journals, ledgers, statements, the trial balance and the print record
    are built for a cycle this content has no part of, and leaving the entry routes open would let
    a student record entries outside the attempt machinery."""
    workspace, student = problem_set
    client.sign_in(student)
    classified = PROBLEM_SET_ENDPOINTS | SHARED_WORKSPACE_ENDPOINTS
    rules = [r for r in _workspace_rules(app) if r.endpoint not in classified]
    assert rules, "no practice-set rules found: this test would prove nothing"

    seen = _walk(app, client, workspace, "problem_set", rules)

    assert seen, "the walk visited nothing"
    assert all(status == 404 for status in seen.values()), \
        f"reachable from a problem set: {sorted(k for k, v in seen.items() if v != 404)}"


def test_the_shared_routes_are_reachable_from_both(app, client, problem_set, practice_set):
    """Guards both tests above from the inside: if the fence 404'd everything, they would pass
    while the application was unusable."""
    # `reference/<section>` is left out: an unknown section 404s for either kind of pack, and a
    # chapter pack declares no reference sections at all. That is the view's own answer about its
    # argument, not the fence's about the pack -- `reference_index` covers the shared path.
    rules = [r for r in _workspace_rules(app)
             if r.endpoint in SHARED_WORKSPACE_ENDPOINTS and "GET" in r.methods
             and "section" not in r.arguments]
    assert rules

    for kind, (workspace, student) in (("problem_set", problem_set),
                                       ("practice_set", practice_set)):
        client.sign_in(student)
        seen = _walk(app, client, workspace, kind, rules)
        blocked = sorted(k for k, v in seen.items() if v == 404)
        assert not blocked, f"{kind}: shared routes 404'd: {blocked}"


def test_a_problem_set_student_can_reach_their_own_problems(app, client, problem_set):
    """The other inside guard: the fence must let the problem-set routes through for the kind they
    are for, or the first test above passes because nothing works anywhere."""
    workspace, student = problem_set
    client.sign_in(student)
    rules = [r for r in _workspace_rules(app)
             if r.endpoint in PROBLEM_SET_ENDPOINTS and "GET" in r.methods]

    seen = _walk(app, client, workspace, "problem_set", rules)

    assert seen
    assert all(status == 200 for status in seen.values()), \
        f"unreachable for the student they are for: {sorted(seen.items())}"


# ── no screen offers a link the fence closes ───────────────────────────────────────────

def test_no_shared_screen_offers_a_link_the_fence_closes(app, client, problem_set):
    """The fence's own consequence, and the general form of it.

    Every shared screen a problem-set student can open -- the overview, how-to-work, hand-in, the
    navigation on all of them -- was written for the practice-set cycle. Once the fence 404s
    Documents, Journals, Ledgers, Statements, the trial balance, Checkpoints and the print record,
    every link to one of those is a dead end on a page the student is meant to use.

    Written as a walk rather than as a list of phrases so a template added later cannot
    reintroduce one quietly.
    """
    workspace, student = problem_set
    client.sign_in(student)
    classified = PROBLEM_SET_ENDPOINTS | SHARED_WORKSPACE_ENDPOINTS
    shared = [r for r in _workspace_rules(app)
              if r.endpoint in SHARED_WORKSPACE_ENDPOINTS and "GET" in r.methods
              and "section" not in r.arguments]
    assert shared, "no shared GET routes found: this test would prove nothing"

    with app.test_request_context():
        slug = _slug(app, workspace)
        # Every URL the fence would refuse, by prefix: `/w/<id>/<slug>/documents`, and so on.
        closed = {}
        for rule in _workspace_rules(app):
            if rule.endpoint in classified:
                continue
            args = {**PLACEHOLDERS["problem_set"], "workspace": workspace.public_id,
                    "company_slug": slug}
            closed[url_for(rule.endpoint, **{k: args[k] for k in rule.arguments})] = rule.endpoint

        offenders = []
        for rule in shared:
            args = {**PLACEHOLDERS["problem_set"], "workspace": workspace.public_id,
                    "company_slug": slug}
            page = url_for(rule.endpoint, **{k: args[k] for k in rule.arguments})
            body = client.get(page).get_data(as_text=True)
            for href, endpoint in closed.items():
                if f'href="{href}"' in body:
                    offenders.append(f"{rule.endpoint} links to {endpoint}")

    assert not offenders, "dead links in a problem set:\n  " + "\n  ".join(sorted(offenders))


# ── A7 is not exempted ─────────────────────────────────────────────────────────────────

def test_a7_still_holds_on_the_problem_screens(app, client, problem_set):
    """The spec allows A7 to be exempted here. It is not, and this is what keeps that true.

    T8.8 and A8 have to go -- a self-grading problem must show the misconception and, behind a
    button, the answer. A7 does not: "matches the expected entry" says everything "correct" would
    say without telling a student they are right or wrong as a person. Keeping it means one fewer
    exemption to fence.
    """
    import re

    workspace, student = problem_set
    client.sign_in(student)
    banned = re.compile(r"\b(correct|incorrect|right|wrong)\b", re.IGNORECASE)
    rules = [r for r in _workspace_rules(app)
             if r.endpoint in PROBLEM_SET_ENDPOINTS and "GET" in r.methods]

    with app.test_request_context():
        for rule in rules:
            args = {**PLACEHOLDERS["problem_set"], "workspace": workspace.public_id,
                    "company_slug": _slug(app, workspace)}
            url = url_for(rule.endpoint, **{k: args[k] for k in rule.arguments})
            body = client.get(url).get_data(as_text=True)
            visible = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body))
            found = banned.search(visible)
            assert not found, f"{rule.endpoint} says {found.group(0)!r} to a student"
