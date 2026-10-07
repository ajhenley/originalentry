"""Is every route scoped, in both directions.

tests/guards/test_structure.py asks whether every route carries its guard. This asks the next
question: whether the guard refuses the right people and admits the right people. Driven off
app.url_map rather than a list, because the first draft of the spec behind this counted
chokepoints instead of enumerating routes and missed twenty-nine of them.
"""

import importlib
import inspect

import pytest
from flask import g, url_for
from flask_login import login_user
from originalentry.decorators import workspace_view
from originalentry.staff.views import _assignment_or_404, _section_or_404

pytestmark = pytest.mark.db

# Routes that are not section-scoped, and WHY. Three different reasons, kept apart: a reviewer
# auditing this list has to be able to tell which one applies to which name.
UNOWNED = {                 # nobody's data; any staff member may see these
    "staff.catalogue": "a company pack belongs to no section",
    "staff.answer_key_print": "an answer key is teaching material, not student data",
}
ADMIN_ONLY = {              # owned, but gated by role rather than by section
    "staff.catalogue_upload": "cohort-wide, so admin-only",
    "staff.people": "staff management",
    "staff.people_add": "staff management",
    "staff.people_role": "staff management",
    "staff.people_sections": "staff management",
}
FILTERED = {                # scoped by what the query returns, not by refusing the request
    "staff.index": "the assignment list is filtered to the sections you teach",
    "staff.assignment_new": "the section dropdown lists only the sections you teach",
    "staff.assignment_create": (
        "verifies the posted section id as a 422 form error, not a 404: the route is reached by "
        "submitting a form, and a 404 on a form you are legitimately filling in is baffling"
    ),
}
EXEMPT = UNOWNED | ADMIN_ONLY | FILTERED

# The three FILTERED routes cannot be walked, so each is covered by a named case instead. Listed
# here so the pairing is auditable from the matrix rather than only from the other file.
FILTERED_COVERED_BY = {
    "staff.index": "test_scoped_console.test_the_assignment_list_shows_only_your_own_sections",
    "staff.assignment_new": "test_scoped_console.test_the_section_dropdown_offers_only_your_own",
    "staff.assignment_create":
        "test_scoped_console.test_a_crafted_create_naming_another_teachers_section_is_refused",
}

# Only needed by the refusal half: both guards abort before any view body reads these.
PLACEHOLDERS = {"key": "sales", "ref": "D01", "entry_id": "1", "statement_type": "trial_balance",
                "kind": "customer", "section": "chart", "run_id": "1",
                "pack_version_id": "1", "variant_code": "A"}

# Routes the admission half cannot judge, and WHY. Each 404s for the section's own teacher on the
# fixture pack for a reason that has nothing to do with scoping, so a 404 here would be a false
# failure. The list was taken from a run of the owner walk made BEFORE anything was scoped, when
# a 404 could not yet mean a refusal; it is not a list of routes that turned out inconvenient.
# The refusal half still walks every one of them, and workspace_view's admission is proved at the
# chokepoint below.
ADMISSION_BLIND = {
    "student.document_image": "the fixture pack is on paper: there is no image to serve",
}


def test_every_exempt_name_is_a_real_route(app):
    """An exempt name matching no endpoint silently stops excluding anything.

    Rename a route and this fails, rather than the allowlist quietly ceasing to mean what it says.
    """
    known = {rule.endpoint for rule in app.url_map.iter_rules()}
    missing = sorted(set(EXEMPT) - known)
    assert not missing, f"exempt names matching no route: {missing}"


def test_every_admin_only_route_is_guarded_by_admin_view(app):
    """ADMIN_ONLY is exempt from the refusal walk, so nothing else asks whether its routes refuse
    a teacher. Swapping @admin_view for @staff_view would let any instructor mint an admin."""
    unguarded = sorted(
        name for name in ADMIN_ONLY
        if not getattr(app.view_functions[name], "_is_admin_view", False))
    assert not unguarded, f"ADMIN_ONLY routes without @admin_view: {unguarded}"


def _scoped_rules(app):
    for rule in app.url_map.iter_rules():
        if not (rule.rule.startswith("/staff") or rule.rule.startswith("/w/")):
            continue
        if rule.endpoint in EXEMPT:
            continue
        yield rule


def _walk(client, app, ids, *, methods=frozenset({"GET", "POST"}), skip=frozenset()):
    """Every scoped route, once per method, with these ids. Returns {"GET staff.x": status}."""
    seen = {}
    with app.test_request_context():
        for rule in _scoped_rules(app):
            if rule.endpoint in skip:
                continue
            args = {**PLACEHOLDERS, **ids}
            url = url_for(rule.endpoint, **{k: args[k] for k in rule.arguments})
            for method in sorted(rule.methods & set(methods)):
                seen[f"{method} {rule.endpoint}"] = client.open(url, method=method).status_code
    return seen


def test_a_teacher_from_another_section_is_refused_everywhere(client, app, foreign, outsider):
    """Placeholder ids suffice: the guard aborts before any view body reads them.

    Both methods, because a leak that writes is the worse one, and a POST here is safe for the
    same reason the placeholders are -- the guard refuses before the view body runs.
    """
    client.sign_in(outsider)
    leaked = [r for r, code in _walk(client, app, foreign).items() if code != 404]
    assert not leaked, "did not refuse a foreign teacher:\n  " + "\n  ".join(leaked)


def test_the_sections_own_teacher_is_refused_nowhere(client, app, worked, owner):
    """The other half, and the half that breaks teaching rather than privacy.

    Without it, an implementation returning 404 to everybody passes the test above clean on every
    route. ``worked`` holds real ids from tests/perfect_student.py, so a 404 here can only mean
    the scoping turned away someone it should have admitted. Any other status -- 200, 302, 400,
    422 -- means the route was entered, which is all this asserts.

    GET only. Walking the POST routes with real ids would release marks, rotate a join code,
    archive a workspace and submit the student's book, in an order that makes every later route
    in the same walk answer differently -- and an early archive turns the rest of the walk into
    404s reported as a refusal. The POST-only routes' admission is proved at the three
    chokepoints instead, below.
    """
    client.sign_in(owner)
    walked = _walk(client, app, worked, methods={"GET"}, skip=ADMISSION_BLIND)
    refused = [r for r, code in walked.items() if code == 404]
    assert not refused, "refused the section's own teacher:\n  " + "\n  ".join(refused)


def test_an_admin_is_refused_nowhere(client, app, worked, admin):
    """An admin teaches nothing and sees everything. GET only, for the reason above."""
    client.sign_in(admin)
    walked = _walk(client, app, worked, methods={"GET"}, skip=ADMISSION_BLIND)
    refused = [r for r, code in walked.items() if code == 404]
    assert not refused, "refused an admin:\n  " + "\n  ".join(refused)


# ── The admission half of the POST-only routes ───────────────────────────────────────────────
# Every POST-only scoped route reaches its subject through one of three chokepoints, so each of
# these stands in for a group of routes the GET walk cannot touch. The test below proves the
# chokepoints really are universal, which is what makes standing in for them legitimate.
#
# They ask for `client` without sending a request: that fixture is what points `db.session` at
# this test's transaction, and without it the lookup would query a connection these rows are not
# visible on and 404 for a reason that is not scoping.

@workspace_view
def _peek_workspace(**kwargs):
    """The smallest possible /w/ view: what the decorator let through."""
    return g.workspace


def _admits_workspace(app, user, ids):
    with app.test_request_context(f"/w/{ids['workspace']}/{ids['company_slug']}/journals"):
        login_user(user)
        return _peek_workspace(workspace=ids["workspace"], company_slug=ids["company_slug"])


def test_workspace_view_admits_the_sections_own_teacher(app, client, worked, owner):
    """Stands in for the ten POST-only /w/ routes (entry_void, post_general, submit_confirm...)."""
    assert _admits_workspace(app, owner, worked).public_id == worked["workspace"]


def test_workspace_view_admits_an_admin(app, client, worked, admin):
    assert _admits_workspace(app, admin, worked).public_id == worked["workspace"]


def test_the_assignment_lookup_admits_the_sections_own_teacher(app, client, worked, owner):
    """Stands in for the ten POST-only /staff/ routes that take an <assignment>."""
    with app.test_request_context():
        login_user(owner)
        assert _assignment_or_404(worked["assignment"]).public_id == worked["assignment"]


def test_the_assignment_lookup_admits_an_admin(app, client, worked, admin):
    with app.test_request_context():
        login_user(admin)
        assert _assignment_or_404(worked["assignment"]).public_id == worked["assignment"]


def test_the_section_lookup_admits_the_sections_own_teacher(app, client, worked, owner):
    """Stands in for the three POST-only /staff/ routes that take an <int:section_id>."""
    with app.test_request_context():
        login_user(owner)
        assert _section_or_404(worked["section_id"]).id == worked["section_id"]


def test_the_section_lookup_admits_an_admin(app, client, worked, admin):
    with app.test_request_context():
        login_user(admin)
        assert _section_or_404(worked["section_id"]).id == worked["section_id"]


def test_every_scoped_console_route_goes_through_one_of_the_two_lookups(app):
    """The test that closes the POST-only gap.

    The three chokepoint tests above stand in for twenty-three POST-only routes, which is only
    worth something if those routes really do reach their subject through a chokepoint. This
    walks the URL map and insists on it, so a new console route taking an <assignment> or a
    <section_id> and looking it up inline is a failure here rather than a silent leak. The
    ``/w/`` third of the same claim is already held by test_structure.py, which requires
    @workspace_view on every /w/ route.

    Source inspection, in the idiom of this repo's other guards: what matters is that the lookup
    is written, and no amount of calling the route proves that for a route whose POST does
    something you cannot undo in a test.
    """
    offenders = []
    for rule in app.url_map.iter_rules():
        if not rule.rule.startswith("/staff/") or rule.endpoint in EXEMPT:
            continue
        if not ({"assignment", "section_id"} & rule.arguments):
            continue
        source = inspect.getsource(app.view_functions[rule.endpoint])
        if "_assignment_or_404(" not in source and "_section_or_404(" not in source:
            offenders.append(rule.endpoint)
    assert not offenders, (
        "console routes that look their subject up without a scoped lookup: " + ", ".join(
            offenders)
    )


def test_every_filtered_route_names_the_case_that_covers_it():
    """FILTERED is the one exemption that is not a refusal, so it has to point somewhere real.

    It is also the hatch a new route with no path argument gets pushed into, which makes it the
    exemption most in need of an anchor. Comparing the two dict literals in this file proves only
    that two literals agree; it has to resolve the name to a callable, so that renaming or
    deleting one of the three cases fails here instead of leaving the matrix green with an
    exemption pointing at nothing.
    """
    module = importlib.import_module("tests.integration.test_scoped_console")
    assert set(FILTERED) == set(FILTERED_COVERED_BY)
    missing = []
    for endpoint, name in sorted(FILTERED_COVERED_BY.items()):
        module_name, _, test_name = name.rpartition(".")
        assert module_name == "test_scoped_console", f"{endpoint}: unknown module {module_name}"
        # test_ prefix as well as callable: `owner` and `create_section` are callable attributes
        # of that module too, so callable() alone would let an exemption point at a fixture or an
        # imported helper and still look anchored.
        if not (test_name.startswith("test_") and callable(getattr(module, test_name, None))):
            missing.append(f"{endpoint} -> {name}")
    assert not missing, "exemptions naming a case that does not exist: " + ", ".join(missing)
