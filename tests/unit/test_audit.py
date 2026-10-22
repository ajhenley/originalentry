"""The durable audit trail's pure parts: who gets logged, and what one row captures.

No database — ``should_audit`` is a plain decision and ``record`` only builds a row and hands it
to the session. The query side (``recent``) and the request hook are exercised against Postgres in
the integration suite."""

from __future__ import annotations

import pytest
from flask import Flask
from originalentry.services import audit


@pytest.mark.parametrize(
    "blueprint, endpoint, role, authed, expected",
    [
        ("staff", "staff.people", "admin", True, True),        # an admin in the console
        ("staff", "staff.grading", "grader", True, True),       # a grader marking
        ("student", "student.journal", "student", True, False),  # a student's own work: not here
        ("auth", "auth.sign_in", None, False, True),            # a sign-in attempt, no user yet
        ("auth", "auth.verify", "student", True, True),          # even a student's auth is logged
        (None, "healthz", "admin", True, False),                 # the health probe is not activity
        ("static", "static", "admin", True, False),              # static files are not activity
        (None, "public.landing", None, False, False),            # anonymous public page: not here
    ],
)
def test_should_audit_decides_who_is_recorded(blueprint, endpoint, role, authed, expected):
    assert audit.should_audit(blueprint, endpoint, role, authed) is expected


# ── a teacher's own practice copy ──────────────────────────────────────────────────────
#
# A teacher works their own assignment in a private practice copy, which is an ordinary workspace
# with a flag. Its traffic is workspace traffic, and the durable trail keeps workspace traffic out
# by design -- the four tests below are the carve-out and its three edges, because this is the
# first per-workspace condition in a function otherwise written about blueprints and roles.


def test_a_teachers_own_practice_traffic_is_not_durably_audited():
    """audit.py's own docstring: logging a student's workspace traffic durably "would make a
    purgeable, PII-light record durable and identifying, which the retention split forbids".
    Practice traffic is workspace traffic. Hours of practice would otherwise be one never-purged
    row per request, all labelled student.*, telling admins the copy exists."""
    # Every role that can own a practice copy: the flag is staff-only, and a grader or an admin
    # who owns one is as much its owner as the instructor who set the assignment.
    for role in ("instructor", "grader", "admin"):
        assert audit.should_audit("student", "student.journal", role, True,
                                  own_practice=True) is False, role


def test_every_other_staff_request_is_still_audited():
    """Guards the carve-out. This is the first per-workspace condition in a function written as a
    pure, shared decision, and the blast radius if it over-matches is the whole trail."""
    # The same role, the same blueprint, the same endpoint -- somebody else's books. The only
    # difference between this and the test above is whose copy it is.
    assert audit.should_audit("student", "student.journal", "instructor", True,
                              own_practice=False) is True
    # The console, where no /w/ route ran and so nothing set the answer.
    assert audit.should_audit("staff", "staff.grading", "grader", True,
                              own_practice=False) is True
    # And a caller that does not pass it at all gets today's answer. The default is False, so a
    # call site that has never heard of practice copies keeps recording, which is the safe
    # direction for a trail: an extra row is noise, a missing one is a gap nothing can refill.
    assert audit.should_audit("staff", "staff.people", "admin", True) is True


def test_a_students_own_traffic_is_still_not_audited():
    """Unchanged by the carve-out, and asked of both answers.

    A student's own workspace traffic was already activity_event's job, and the new parameter must
    not become what decides it -- a flagged workspace owned by a student is an invariant breach
    ``services.practice`` refuses to create on every path, and the trail must not start depending
    on that refusal holding.
    """
    assert audit.should_audit("student", "student.journal", "student", True) is False
    assert audit.should_audit("student", "student.journal", "student", True,
                              own_practice=True) is False


def test_the_auth_blueprint_is_still_always_audited():
    """The carve-out sits below the auth branch, deliberately.

    Authentication is recorded for everybody who attempts it, whoever they are and whether or not
    they succeed -- a failed sign-in has no user yet. A per-workspace condition that could switch
    that off would be a way to sign in unrecorded, so the ordering is asserted rather than left to
    the fact that no auth route happens to load a workspace today.
    """
    assert audit.should_audit("auth", "auth.sign_in", None, False, own_practice=True) is True
    assert audit.should_audit("auth", "auth.verify", "instructor", True,
                              own_practice=True) is True


class _Actor:
    id = 7
    email = "instructor@college.edu"
    role = "instructor"


class _FakeSession:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)


def test_record_snapshots_the_actor_and_hashes_the_ip():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "test-secret"
    session = _FakeSession()

    with app.app_context():
        row = audit.record(
            session, action="staff.answer_key_print", actor=_Actor(),
            method="GET", status=200, ip="203.0.113.7", detail={"pack_version_id": 3},
        )

    assert session.added == [row]
    assert row.actor_id == 7
    assert row.actor_label == "instructor@college.edu"  # snapshotted, so it outlives the account
    assert row.actor_role == "instructor"
    assert row.action == "staff.answer_key_print"
    assert row.method == "GET" and row.status == 200
    assert row.detail == {"pack_version_id": 3}
    # The IP is stored one-way, never raw.
    assert row.ip_hash and row.ip_hash != "203.0.113.7"


def test_record_tolerates_an_anonymous_actor_and_no_ip():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "test-secret"
    session = _FakeSession()

    with app.app_context():
        row = audit.record(session, action="auth.sign_in", actor=None, method="POST", status=200)

    assert row.actor_id is None
    assert row.actor_label is None
    assert row.actor_role is None
    assert row.ip_hash is None
