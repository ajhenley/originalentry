"""Multi-company: a student chooses a company and works in it, gated by section availability
(M1.4, M2.3, tension 4). Withdrawing a company stops new workspaces but leaves open ones usable
(A22). Every workspace pins its own pack version, so two students' books never cross (A20/A23).
"""

import copy
import secrets

import pytest
from originalentry.models import (
    Enrollment,
    PackVersion,
    Section,
    SectionStaff,
    User,
    Workspace,
)
from originalentry.packs import schema
from originalentry.packs.importer import import_content
from originalentry.services import multicompany
from originalentry.services.assignments import create_assignment
from originalentry.services.multicompany import ChoiceRefused, choose_company, set_availability
from sqlalchemy import func, select

from tests.packs import testco_alpha

pytestmark = pytest.mark.db


def _pack(session, slug):
    data = copy.deepcopy(testco_alpha.PACK)
    data["company"]["slug"] = slug
    data["company"]["name"] = slug.replace("-", " ").title()
    return import_content(session, schema.load_pack(data), source_sha256=secrets.token_hex(32))


def _setup(session):
    pv_a = _pack(session, f"alpha-{secrets.token_hex(3)}")
    pv_b = _pack(session, f"beta-{secrets.token_hex(3)}")
    section = Section(name="Sec", join_code=f"J{secrets.token_hex(3).upper()}")
    student = User(email=f"s-{secrets.token_hex(3)}@example.edu", role="student")
    session.add_all([section, student])
    session.flush()
    session.add(Enrollment(section_id=section.id, user_id=student.id))
    assignment = create_assignment(
        session, section=section, title="Choose one",
        choice_pack_versions=[pv_a, pv_b],
    )
    session.flush()
    return section, student, assignment, pv_a, pv_b


def test_choice_assignment_offers_both_companies(session):
    _, _, assignment, pv_a, pv_b = _setup(session)
    assert assignment.company_policy == "choice"
    assert assignment.fixed_pack_version_id is None
    offered = {o.pack_version_id for o in multicompany.company_options(session, assignment)}
    assert offered == {pv_a.id, pv_b.id}


def test_choosing_opens_a_workspace_pinned_to_that_company(session):
    _, student, assignment, pv_a, _ = _setup(session)
    ws = choose_company(session, assignment, student, pack_version_id=pv_a.id)
    assert ws.pack_version_id == pv_a.id
    assert ws.variant_id is not None
    # Idempotent: choosing again returns the same workspace, not a second one.
    again = choose_company(session, assignment, student, pack_version_id=pv_a.id)
    assert again.id == ws.id
    count = session.execute(
        select(func.count()).select_from(Workspace).where(
            Workspace.assignment_id == assignment.id, Workspace.student_id == student.id
        )
    ).scalar_one()
    assert count == 1


def test_a_company_not_offered_is_refused(session):
    _, student, assignment, _, _ = _setup(session)
    other = _pack(session, f"gamma-{secrets.token_hex(3)}")
    with pytest.raises(ChoiceRefused):
        choose_company(session, assignment, student, pack_version_id=other.id)


def test_withdrawn_company_cannot_be_chosen(session):
    section, student, assignment, pv_a, _ = _setup(session)
    set_availability(session, section_id=section.id,
                     content_pack_id=pv_a.content_pack_id, available=False)
    with pytest.raises(ChoiceRefused):
        choose_company(session, assignment, student, pack_version_id=pv_a.id)


def test_withdrawing_after_choice_leaves_the_workspace_usable(session):
    """A22: availability is checked only when opening books, never mid-work."""
    section, student, assignment, pv_a, _ = _setup(session)
    ws = choose_company(session, assignment, student, pack_version_id=pv_a.id)

    set_availability(session, section_id=section.id,
                     content_pack_id=pv_a.content_pack_id, available=False)
    session.flush()

    still_there = session.get(Workspace, ws.id)
    assert still_there.archived_at is None
    # It still loads through the engine — books already open keep working.
    from originalentry.ledger.snapshot import load_snapshot
    snapshot = load_snapshot(session, still_there)
    assert snapshot.accounts  # the chart is intact


def test_two_students_get_isolated_companies(session):
    section, student_a, assignment, pv_a, pv_b = _setup(session)
    student_b = User(email=f"b-{secrets.token_hex(3)}@example.edu", role="student")
    session.add(student_b)
    session.flush()
    session.add(Enrollment(section_id=section.id, user_id=student_b.id))

    ws_a = choose_company(session, assignment, student_a, pack_version_id=pv_a.id)
    ws_b = choose_company(session, assignment, student_b, pack_version_id=pv_b.id)
    assert ws_a.pack_version_id == pv_a.id
    assert ws_b.pack_version_id == pv_b.id
    assert ws_a.pack_version_id != ws_b.pack_version_id


def test_staff_creates_a_choice_assignment(client, session):
    from originalentry.models import Assignment, AssignmentChoice

    pv_a = _pack(session, f"alpha-{secrets.token_hex(3)}")
    pv_b = _pack(session, f"beta-{secrets.token_hex(3)}")
    section = Section(name="Sec", join_code=f"C{secrets.token_hex(3).upper()}")
    instructor = User(email=f"i-{secrets.token_hex(3)}@example.edu", role="instructor")
    session.add_all([section, instructor])
    session.flush()
    # The instructor teaches this section. Without the row, scoped visibility (Task 4)
    # refuses them from their own class.
    session.add(SectionStaff(section_id=section.id, user_id=instructor.id))
    session.flush()
    client.sign_in(instructor)

    resp = client.post("/staff/assignments/new", data={
        "title": "Pick a company", "section_choice": "existing", "section_id": str(section.id),
        "company_policy": "choice",
        "choice_pack_version_ids": [str(pv_a.id), str(pv_b.id)],
        "mode": "screen", "variant_policy": "round_robin", "late_policy": "closed",
    })
    assert resp.status_code == 302
    assignment = session.scalars(
        select(Assignment).where(Assignment.section_id == section.id)
    ).one()
    assert assignment.company_policy == "choice" and assignment.fixed_pack_version_id is None
    offered = session.scalars(
        select(AssignmentChoice.pack_version_id).where(
            AssignmentChoice.assignment_id == assignment.id)
    ).all()
    assert set(offered) == {pv_a.id, pv_b.id}


def test_http_choose_flow(client, session):
    section, student, assignment, pv_a, pv_b = _setup(session)
    a_name = session.get(PackVersion, pv_a.id)  # ensure loaded
    assert a_name is not None
    client.sign_in(student)

    page = client.get(f"/a/{assignment.public_id}/choose")
    assert page.status_code == 200
    body = page.get_data(as_text=True)
    assert "Choose one" in body

    resp = client.post(f"/a/{assignment.public_id}/choose",
                       data={"pack_version_id": str(pv_a.id)})
    assert resp.status_code == 302
    ws = session.scalars(
        select(Workspace).where(Workspace.student_id == student.id,
                                Workspace.assignment_id == assignment.id)
    ).one()
    assert ws.pack_version_id == pv_a.id


# ── M2.4: the choice is recorded, and locks at the first entry ──────────────────────────
#
# Not at the moment of choosing. A student who clicks the wrong company and has recorded nothing
# should be able to put it right themselves — the same mistake as pressing Submit too early, and
# it should not need an instructor either.

def _record_something(session, workspace, student):
    from datetime import date

    from originalentry.forms.entries import EntryCommand, LineCommand
    from originalentry.services import workspace_write
    from originalentry.services.entries import record_entry

    command = EntryCommand(
        journal_key="general", kind="regular", document_ref="INV-1",
        entry_date=date(2026, 12, 2), description=None,
        lines=[LineCommand("112", "C-ONE", 120000, 0), LineCommand("401", None, 0, 120000)],
        client_key="m24",
    )
    workspace_write(session, workspace.public_id, student, activity_kind="save",
                    mutate=lambda s, w: record_entry(s, w, command))


def test_choosing_records_when_they_chose(session):
    _, student, assignment, pv_a, _ = _setup(session)

    workspace = choose_company(session, assignment, student, pack_version_id=pv_a.id)

    assert workspace.company_chosen_at is not None


def test_a_student_who_has_recorded_nothing_can_change_their_mind(session):
    _, student, assignment, pv_a, pv_b = _setup(session)
    first = choose_company(session, assignment, student, pack_version_id=pv_a.id)

    second = choose_company(session, assignment, student, pack_version_id=pv_b.id)

    assert second.pack_version_id == pv_b.id
    assert second.variant_id is not None          # a variant for the company they are now in
    assert second.id == first.id                  # the same empty books, pointed elsewhere


def test_changing_their_mind_is_recorded_again(session):
    _, student, assignment, pv_a, pv_b = _setup(session)
    workspace = choose_company(session, assignment, student, pack_version_id=pv_a.id)
    first_chose = workspace.company_chosen_at

    choose_company(session, assignment, student, pack_version_id=pv_b.id)

    assert workspace.company_chosen_at >= first_chose


def test_choosing_the_same_company_twice_changes_nothing(session):
    _, student, assignment, pv_a, _ = _setup(session)
    first = choose_company(session, assignment, student, pack_version_id=pv_a.id)

    again = choose_company(session, assignment, student, pack_version_id=pv_a.id)

    assert again.id == first.id
    assert again.pack_version_id == pv_a.id


def test_once_they_have_recorded_something_the_choice_is_theirs_to_keep(session):
    _, student, assignment, pv_a, pv_b = _setup(session)
    workspace = choose_company(session, assignment, student, pack_version_id=pv_a.id)
    _record_something(session, workspace, student)

    with pytest.raises(ChoiceRefused):
        choose_company(session, assignment, student, pack_version_id=pv_b.id)

    assert workspace.pack_version_id == pv_a.id


def test_the_work_they_did_is_never_touched_by_a_refused_change(session):
    """The cardinal sin would be losing the entries while switching them to another company."""
    from originalentry.models import JournalEntry

    _, student, assignment, pv_a, pv_b = _setup(session)
    workspace = choose_company(session, assignment, student, pack_version_id=pv_a.id)
    _record_something(session, workspace, student)

    with pytest.raises(ChoiceRefused):
        choose_company(session, assignment, student, pack_version_id=pv_b.id)

    kept = session.execute(
        select(func.count()).select_from(JournalEntry)
        .where(JournalEntry.workspace_id == workspace.id)
    ).scalar_one()
    assert kept == 1


def test_triage_alone_counts_as_having_started(session):
    """Deciding a document needs no entry is work, even though it writes no entry."""
    from originalentry.services import workspace_write
    from originalentry.services.dispositions import set_disposition

    _, student, assignment, pv_a, pv_b = _setup(session)
    workspace = choose_company(session, assignment, student, pack_version_id=pv_a.id)
    workspace_write(session, workspace.public_id, student, activity_kind="disposition",
                    mutate=lambda s, w: set_disposition(s, w, "INV-1", "no_entry", "A quotation"))

    with pytest.raises(ChoiceRefused):
        choose_company(session, assignment, student, pack_version_id=pv_b.id)


def test_the_choice_screen_is_still_reachable_before_they_start(client, session):
    """The service allows a change of mind; the screen has to let them ask for one."""
    _, student, assignment, pv_a, _ = _setup(session)
    choose_company(session, assignment, student, pack_version_id=pv_a.id)
    session.commit()
    client.sign_in(student)

    response = client.get(f"/a/{assignment.public_id}/choose")

    assert response.status_code == 200
    assert "Choose" in response.get_data(as_text=True)


def test_once_they_start_the_choice_screen_takes_them_to_their_books(client, session):
    _, student, assignment, pv_a, _ = _setup(session)
    workspace = choose_company(session, assignment, student, pack_version_id=pv_a.id)
    _record_something(session, workspace, student)
    session.commit()
    client.sign_in(student)

    response = client.get(f"/a/{assignment.public_id}/choose")

    assert response.status_code in (302, 303)
    assert workspace.public_id in response.headers["Location"]


def test_the_screen_shows_which_one_they_picked(client, session):
    _, student, assignment, pv_a, _ = _setup(session)
    choose_company(session, assignment, student, pack_version_id=pv_a.id)
    session.commit()
    client.sign_in(student)

    body = client.get(f"/a/{assignment.public_id}/choose").get_data(as_text=True)

    assert "The one you picked" in body
    assert "still change it" in body
