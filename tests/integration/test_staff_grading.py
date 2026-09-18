"""The Grading screen (I3.1–I3.7).

Marking is automatic, but the instructor's judgement is not: the engine shows what it credited and
why, flags what it could not decide, and every override records a reason. Releasing marks is one
action for the whole section.
"""

import pytest
from parchment.models import Assignment, Section, StaffAction, User, Variant, Workspace
from parchment.packs import schema
from parchment.packs.importer import import_answer_keys, import_content
from parchment.services import workspace_write
from parchment.services.dispositions import set_disposition
from parchment.services.grades import final_marks, latest_run
from sqlalchemy import select

from tests.packs import testco_alpha

pytestmark = pytest.mark.db


@pytest.fixture
def section(session, client):
    pv = import_content(session, schema.load_pack(testco_alpha.PACK), source_sha256="q" * 64)
    import_answer_keys(session, pv, {"A": schema.load_answer_key(testco_alpha.KEY_A)})
    variant = session.scalars(select(Variant).where(Variant.pack_version_id == pv.id)).first()
    sec = Section(name="ACCT 1010-03", join_code="grading-join")
    instructor = User(email="grading-instructor@example.edu", role="instructor")
    session.add_all([sec, instructor])
    session.flush()
    assignment = Assignment(section_id=sec.id, title="December cycle", company_policy="fixed",
                            fixed_pack_version_id=pv.id)
    session.add(assignment)
    session.flush()

    workspaces = []
    for email in ("first@example.edu", "second@example.edu"):
        student = User(email=email, given_name="Sam", family_name=email[0].upper())
        session.add(student)
        session.flush()
        ws = Workspace(assignment_id=assignment.id, student_id=student.id, pack_version_id=pv.id,
                       variant_id=variant.id, status="in_progress")
        session.add(ws)
        session.flush()
        workspaces.append((ws, student))
    return assignment, workspaces, instructor


def _grading_url(assignment, suffix=""):
    return f"/staff/grading/{assignment.public_id}{suffix}"


def test_before_any_run_the_list_says_nobody_has_been_graded(client, section):
    assignment, _, instructor = section
    client.sign_in(instructor)

    body = client.get(_grading_url(assignment)).get_data(as_text=True)

    assert "Not graded" in body
    assert "Grade" in body  # the action that starts it


def test_running_grading_marks_the_section_and_shows_the_totals(client, section, session):
    assignment, workspaces, instructor = section
    ws, student = workspaces[0]
    workspace_write(session, ws.public_id, student, activity_kind="disposition",
                    mutate=lambda s, w: set_disposition(s, w, "INV-1", "record", None))
    client.sign_in(instructor)

    response = client.post(_grading_url(assignment, "/run"), follow_redirects=True)

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Graded 2" in body
    assert "of 100" in body
    for workspace, _ in workspaces:
        assert latest_run(session, workspace) is not None


def test_the_detail_screen_shows_what_the_rule_credited(client, section, session):
    assignment, workspaces, instructor = section
    ws, student = workspaces[0]
    workspace_write(session, ws.public_id, student, activity_kind="disposition",
                    mutate=lambda s, w: set_disposition(s, w, "INV-1", "record", None))
    client.sign_in(instructor)
    client.post(_grading_url(assignment, "/run"), follow_redirects=True)

    body = client.get(_grading_url(assignment, f"/{ws.public_id}")).get_data(as_text=True)

    assert "Document triage" in body
    assert "INV-1" in body            # the evidence, item by item
    assert "Handled as recorded" in body


def test_an_override_changes_the_mark_and_is_recorded_as_a_staff_action(client, section, session):
    assignment, workspaces, instructor = section
    ws, _ = workspaces[0]
    client.sign_in(instructor)
    client.post(_grading_url(assignment, "/run"), follow_redirects=True)

    response = client.post(
        _grading_url(assignment, f"/{ws.public_id}/override"),
        data={"component_key": "triage", "points": "8", "reason": "Marked by hand on appeal"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    marks = final_marks(session, ws)
    triage = next(c for c in marks.components if c.key == "triage")
    assert triage.points == 8.0
    assert triage.reason == "Marked by hand on appeal"
    action = session.scalars(
        select(StaffAction).where(StaffAction.action == "grade_override")
    ).first()
    assert action is not None
    assert action.target_id == ws.id


def test_an_override_without_a_reason_is_refused(client, section, session):
    assignment, workspaces, instructor = section
    ws, _ = workspaces[0]
    client.sign_in(instructor)
    client.post(_grading_url(assignment, "/run"), follow_redirects=True)

    response = client.post(
        _grading_url(assignment, f"/{ws.public_id}/override"),
        data={"component_key": "triage", "points": "8", "reason": "   "},
        follow_redirects=True,
    )

    assert "records why" in response.get_data(as_text=True)
    marks = final_marks(session, ws)
    assert not any(c.overridden for c in marks.components)


def test_a_comment_is_saved_for_the_student(client, section, session):
    assignment, workspaces, instructor = section
    ws, _ = workspaces[0]
    client.sign_in(instructor)
    client.post(_grading_url(assignment, "/run"), follow_redirects=True)

    client.post(_grading_url(assignment, f"/{ws.public_id}/comment"),
                data={"body": "Your subsidiary proof was tidy."}, follow_redirects=True)

    assert final_marks(session, ws).comment == "Your subsidiary proof was tidy."


def test_releasing_marks_opens_them_to_the_whole_section_once(client, section, session):
    assignment, workspaces, instructor = section
    client.sign_in(instructor)
    client.post(_grading_url(assignment, "/run"), follow_redirects=True)

    response = client.post(_grading_url(assignment, "/release"), follow_redirects=True)

    assert "released" in response.get_data(as_text=True).lower()
    session.refresh(assignment)
    assert assignment.marks_released_at is not None
    action = session.scalars(
        select(StaffAction).where(StaffAction.action == "release_marks")
    ).first()
    assert action is not None


def test_the_review_queue_lists_only_what_the_engine_could_not_decide(client, section, session):
    assignment, workspaces, instructor = section
    ws, student = workspaces[0]
    # Two live entries for one document: the engine credits what it can and asks for a human.
    from datetime import date

    from parchment.forms.entries import EntryCommand, LineCommand
    from parchment.services.entries import record_entry

    for client_key in ("dup-1", "dup-2"):
        command = EntryCommand(
            journal_key="general", kind="regular", document_ref="INV-1",
            entry_date=date(2026, 12, 2), description=None,
            lines=[LineCommand("112", "C-ONE", 120000, 0), LineCommand("401", None, 0, 120000)],
            client_key=client_key,
        )
        workspace_write(session, ws.public_id, student, activity_kind="save",
                        mutate=lambda s, w, c=command: record_entry(s, w, c))
    client.sign_in(instructor)
    client.post(_grading_url(assignment, "/run"), follow_redirects=True)

    body = client.get(_grading_url(assignment, "?filter=review")).get_data(as_text=True)

    assert "Sam F" in body           # the student whose work needs a look
    assert "second@example.edu" not in body
