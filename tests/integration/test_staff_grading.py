"""The Grading screen (I3.1–I3.7).

Marking is automatic, but the instructor's judgement is not: the engine shows what it credited and
why, flags what it could not decide, and every override records a reason. Releasing marks is one
action for the whole section.
"""

import pytest
from originalentry.models import (
    Assignment,
    Section,
    SectionStaff,
    StaffAction,
    User,
    Variant,
    Workspace,
)
from originalentry.packs import schema
from originalentry.packs.importer import import_answer_keys, import_content
from originalentry.services import workspace_write
from originalentry.services.dispositions import set_disposition
from originalentry.services.grades import final_marks, latest_run
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
    # The instructor teaches this section. Without the row, scoped visibility (Task 4)
    # refuses them from their own class.
    session.add(SectionStaff(section_id=sec.id, user_id=instructor.id))
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
        select(StaffAction).where(StaffAction.action == "grade_override",
                                  StaffAction.target_id == ws.id)
    ).first()
    assert action is not None


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
        select(StaffAction).where(StaffAction.action == "release_marks",
                                  StaffAction.target_id == assignment.id)
    ).first()
    assert action is not None


def test_the_review_queue_lists_only_what_the_engine_could_not_decide(client, section, session):
    assignment, workspaces, instructor = section
    ws, student = workspaces[0]
    # Two live entries for one document: the engine credits what it can and asks for a human.
    from datetime import date

    from originalentry.forms.entries import EntryCommand, LineCommand
    from originalentry.services.entries import record_entry

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


def test_diagnostics_reports_the_cohort_and_exports_it(client, section, session):
    """I4: counts, not accusations — and a CSV the instructor can take away."""
    assignment, workspaces, instructor = section
    client.sign_in(instructor)
    client.post(_grading_url(assignment, "/run"), follow_redirects=True)

    page = client.get(f"/staff/diagnostics/{assignment.public_id}")
    body = page.get_data(as_text=True)
    assert page.status_code == 200
    assert "Recorded a sale in an expense account" in body   # every designed error is listed
    assert "Time on task" in body

    export = client.get(f"/staff/diagnostics/{assignment.public_id}/export.csv")
    assert export.status_code == 200
    assert "text/csv" in export.headers["Content-Type"]
    assert "attachment" in export.headers["Content-Disposition"]
    lines = export.get_data(as_text=True).strip().splitlines()
    assert lines[0].startswith("email,family_name,given_name,variant")
    assert len(lines) == 3  # a header and the two students


def test_the_screen_explains_a_total_that_is_not_the_sum_of_its_rows(client, section, session):
    """A deduction the pack asked for (T8.5). An unexplained total is worse than none."""
    from dataclasses import replace

    from originalentry.grading.models import Deduction
    from originalentry.grading.workspace import grade_workspace
    from originalentry.services.grades import record_run

    assignment, workspaces, instructor = section
    ws, student = workspaces[0]
    workspace_write(session, ws.public_id, student, activity_kind="disposition",
                    mutate=lambda s, w: set_disposition(s, w, "INV-1", "record", None))
    result = replace(
        grade_workspace(session, ws),
        deductions=(Deduction("sale_to_an_expense_account", "Recorded a sale in an expense", 4.0),),
    )
    record_run(session, ws, result, created_by=instructor)
    client.sign_in(instructor)

    body = client.get(_grading_url(assignment, f"/{ws.public_id}")).get_data(as_text=True)

    assert "earned, less" in body
    assert "Recorded a sale in an expense" in body


# ── Grading a section a few at a time (T8.6) ────────────────────────────────────────────
#
# The button posts once and grades a batch. `batch.js` keeps posting until there are none left,
# which it can only do if the answer says how many remain. Without the script the same endpoint
# still works as an ordinary form post — that is what the first of these checks.

def test_without_the_script_the_button_still_grades_a_batch(client, section, session):
    assignment, workspaces, instructor = section
    client.sign_in(instructor)

    response = client.post(_grading_url(assignment, "/run"), follow_redirects=False)

    assert response.status_code in (302, 303)     # an ordinary post, an ordinary redirect
    assert latest_run(session, workspaces[0][0]) is not None


def test_a_batch_request_is_told_how_much_is_left(client, section):
    assignment, workspaces, instructor = section
    client.sign_in(instructor)

    response = client.post(_grading_url(assignment, "/run"), headers={"X-Batch": "1"})

    assert response.status_code == 200
    assert int(response.headers["X-Total"]) == len(workspaces)
    assert int(response.headers["X-Graded"]) == len(workspaces)
    assert int(response.headers["X-Remaining"]) == 0


def test_the_remaining_count_falls_to_zero_and_stays_there(client, section):
    """What lets the script stop: a second run of a graded section has nothing left to do."""
    assignment, _, instructor = section
    client.sign_in(instructor)
    client.post(_grading_url(assignment, "/run"), headers={"X-Batch": "1"})

    again = client.post(_grading_url(assignment, "/run"), headers={"X-Batch": "1"})

    assert int(again.headers["X-Remaining"]) == 0


def test_the_screen_offers_the_bar_and_the_count(client, section):
    assignment, _, instructor = section
    client.sign_in(instructor)

    body = client.get(_grading_url(assignment)).get_data(as_text=True)

    assert "data-batch" in body
    assert "<progress" in body
    assert "batch.js" in body


def test_the_cursor_walks_the_section_instead_of_regrading_the_front_of_it(client, section,
                                                                           session):
    """What the script sends back. With a batch of one, two posts must reach two workspaces."""
    assignment, workspaces, instructor = section
    client.sign_in(instructor)

    first = client.post(_grading_url(assignment, "/run"), headers={"X-Batch": "1"},
                        data={"after": ""})
    cursor = first.headers["X-After"]
    second = client.post(_grading_url(assignment, "/run"), headers={"X-Batch": "1"},
                         data={"after": cursor})

    assert cursor
    # The second batch starts past the first, so it grades nothing it has already done.
    assert int(second.headers["X-Graded"]) == 0
    assert int(second.headers["X-Remaining"]) == 0
    for workspace, _ in workspaces:
        assert latest_run(session, workspace) is not None
