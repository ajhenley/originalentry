"""Handing out variants by hand (I1.3).

An assignment can give out its variants in turn, at random, or by hand. "By hand" is for the
instructor who wants to know exactly who has which figures — a resit, or two students sitting
together.

Until the instructor says, that student has no figures, and the app has to say so in those words.
Before this, a student in a manual assignment was told their work was read-only "because the
assignment has been submitted", which was not true and left them with nowhere to go.
"""

import secrets
from datetime import date

import pytest
from originalentry.forms.entries import EntryCommand, LineCommand
from originalentry.models import Section, SectionStaff, StaffAction, User, Variant
from originalentry.packs import schema
from originalentry.packs.importer import import_content
from originalentry.services import WriteRefused, workspace_write
from originalentry.services.assignments import MANUAL, create_assignment, open_workspace
from originalentry.services.entries import record_entry
from originalentry.services.variants import VariantRefused, assign_variant
from sqlalchemy import select

from tests.packs import testco_alpha

pytestmark = pytest.mark.db


def _two_variant_pack() -> dict:
    """The fixture company ships one variant; handing one out by hand needs a second to move to."""
    import copy

    data = copy.deepcopy(testco_alpha.PACK)
    data["company"]["slug"] = f"mv-{secrets.token_hex(3)}"
    data["variants"] = [*data["variants"], {"code": "B", "label": "Variant B", "drivers": {}}]
    data["opening_balances"]["B"] = copy.deepcopy(data["opening_balances"]["A"])
    return data


@pytest.fixture
def manual(session, client):
    pv = import_content(session, schema.load_pack(_two_variant_pack()),
                        source_sha256=secrets.token_hex(32))
    section = Section(name="Sec", join_code=f"V{secrets.token_hex(3).upper()}")
    student = User(email=f"mv-{secrets.token_hex(3)}@example.edu", role="student",
                   given_name="Ada", family_name="Sowande")
    instructor = User(email=f"mvi-{secrets.token_hex(3)}@example.edu", role="instructor")
    session.add_all([section, student, instructor])
    session.flush()
    # The instructor teaches this section. Without the row, scoped visibility (Task 4)
    # refuses them from their own class.
    session.add(SectionStaff(section_id=section.id, user_id=instructor.id))
    session.flush()
    assignment = create_assignment(session, section=section, title="December",
                                   pack_version=pv, variant_policy=MANUAL)
    workspace = open_workspace(session, assignment, student)
    return workspace, student, assignment, instructor, pv


def _record(session, ws, student):
    command = EntryCommand(
        journal_key="general", kind="regular", document_ref="INV-1",
        entry_date=date(2026, 12, 2), description=None,
        lines=[LineCommand("112", "C-ONE", 120000, 0), LineCommand("401", None, 0, 120000)],
        client_key="mv-1",
    )
    workspace_write(session, ws.public_id, student, activity_kind="save",
                    mutate=lambda s, w: record_entry(s, w, command))


def test_a_manual_assignment_hands_out_no_variant_on_its_own(session, manual):
    workspace, _, _, _, _ = manual

    assert workspace.variant_id is None


def test_the_student_is_told_the_truth_about_why_they_cannot_record(session, manual):
    """Not "the assignment has been submitted", which is what it used to say."""
    workspace, student, _, _, _ = manual

    with pytest.raises(WriteRefused) as refused:
        _record(session, workspace, student)

    said = str(refused.value).lower()
    assert "submitted" not in said
    assert "instructor" in said


def test_assigning_one_lets_them_work(session, manual):
    workspace, student, _, instructor, pv = manual
    code = session.scalars(select(Variant.code).where(Variant.pack_version_id == pv.id)).first()

    assign_variant(session, workspace, code, actor=instructor)

    assert workspace.variant_id is not None
    _record(session, workspace, student)


def test_the_instructor_who_assigned_it_is_recorded(session, manual):
    workspace, _, _, instructor, pv = manual
    code = session.scalars(select(Variant.code).where(Variant.pack_version_id == pv.id)).first()

    assign_variant(session, workspace, code, actor=instructor)

    action = session.scalars(
        select(StaffAction).where(StaffAction.action == "assign_variant",
                                  StaffAction.target_id == workspace.id)
    ).one()
    assert action.detail["variant"] == code


def test_a_variant_from_another_company_is_refused(session, manual):
    """Handing out figures that belong to another company is the one thing to get wrong here."""
    workspace, _, _, instructor, _ = manual

    with pytest.raises(VariantRefused):
        assign_variant(session, workspace, "NOT-A-VARIANT", actor=instructor)

    assert workspace.variant_id is None


def test_changing_it_once_they_have_started_is_refused(session, manual):
    """Their figures would change under them, and everything recorded would be against the old."""
    workspace, student, _, instructor, pv = manual
    codes = list(session.scalars(select(Variant.code).where(Variant.pack_version_id == pv.id)))
    assign_variant(session, workspace, codes[0], actor=instructor)
    _record(session, workspace, student)

    with pytest.raises(VariantRefused):
        assign_variant(session, workspace, codes[-1], actor=instructor)


def test_assigning_the_same_one_again_changes_nothing(session, manual):
    workspace, _, _, instructor, pv = manual
    code = session.scalars(select(Variant.code).where(Variant.pack_version_id == pv.id)).first()
    assign_variant(session, workspace, code, actor=instructor)
    chosen = workspace.variant_id

    assign_variant(session, workspace, code, actor=instructor)

    assert workspace.variant_id == chosen


# ── The screen ──────────────────────────────────────────────────────────────────────────

def test_progress_says_who_is_still_waiting(client, session, manual):
    workspace, _, assignment, instructor, _ = manual
    session.commit()
    client.sign_in(instructor)

    body = client.get(f"/staff/progress/{assignment.public_id}").get_data(as_text=True)

    assert "Waiting for a variant" in body
    assert workspace.public_id in body


def test_an_instructor_assigns_one_from_progress(client, session, manual):
    workspace, _, assignment, instructor, pv = manual
    code = session.scalars(select(Variant.code).where(Variant.pack_version_id == pv.id)).first()
    session.commit()
    client.sign_in(instructor)

    response = client.post(
        f"/staff/progress/{assignment.public_id}/variant",
        data={"workspace": workspace.public_id, "variant": code},
        follow_redirects=True,
    )

    assert response.status_code == 200
    session.refresh(workspace)
    assert workspace.variant_id is not None


def test_a_student_still_waiting_is_not_marked_zero(session, manual):
    """They were never given figures. Marking them out of a hundred for that would be a lie the
    engine tells about work nobody could have done."""
    from originalentry.services.grades import grade_section, latest_run, ungraded_count

    workspace, _, assignment, instructor, _ = manual

    graded, total, _ = grade_section(session, assignment, actor=instructor)

    assert total == 0                         # nobody in this section is gradable yet
    assert graded == []
    assert latest_run(session, workspace) is None
    assert ungraded_count(session, assignment) == 0   # and the batch run does not stall on them
