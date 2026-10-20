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
