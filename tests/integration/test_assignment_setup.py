"""Setting a term up (I1.1–I1.6, A13, A14).

An instructor must be able to start a term without anyone opening a database session: make a
section, make an assignment on a company from the catalogue, hand out a join code, and have a
student enrolled and working. Cloning last term's assignment with new dates is one action.
"""

import copy
import re
from datetime import UTC, datetime, timedelta

import pytest
from originalentry.models import (
    Assignment,
    Enrollment,
    Section,
    SectionStaff,
    User,
    Variant,
    Workspace,
)
from originalentry.packs import schema
from originalentry.packs.importer import import_answer_keys, import_content
from originalentry.services.assignments import (
    JoinRefused,
    clone_assignment,
    create_assignment,
    create_section,
    join_with_code,
    rotate_join_code,
)
from sqlalchemy import func, select

from tests.packs import testco_alpha

pytestmark = pytest.mark.db

DUE = datetime(2026, 12, 18, 23, 59, tzinfo=UTC)


@pytest.fixture
def catalogue(session):
    pack_version = import_content(session, schema.load_pack(testco_alpha.PACK),
                                  source_sha256="setup" + "0" * 59)
    import_answer_keys(session, pack_version,
                       {"A": schema.load_answer_key(testco_alpha.KEY_A)})
    instructor = User(email="setup-instructor@example.edu", role="instructor")
    session.add(instructor)
    session.flush()
    return pack_version, instructor


def test_a_section_gets_a_join_code_nobody_has_to_invent(session, catalogue):
    _, instructor = catalogue

    section = create_section(session, name="ACCT 1010-04", term="Fall 2026", actor=instructor)

    assert section.join_code
    assert section.join_code_active
    assert len(section.join_code) >= 6
    assert not set(section.join_code) & set("O0I1")  # nothing a student can mistype


def test_an_assignment_names_one_company_and_its_dates(session, catalogue):
    pack_version, instructor = catalogue
    section = create_section(session, name="Sec", term="Fall 2026", actor=instructor)

    assignment = create_assignment(
        session, section=section, title="December cycle", pack_version=pack_version,
        mode="paper", due_at=DUE, actor=instructor,
    )

    assert assignment.public_id
    assert assignment.fixed_pack_version_id == pack_version.id
    assert assignment.company_policy == "fixed"
    assert assignment.mode == "paper"
    assert assignment.due_at == DUE


def test_cloning_carries_the_settings_and_moves_the_dates(session, catalogue):
    pack_version, instructor = catalogue
    section = create_section(session, name="Sec", term="Fall 2026", actor=instructor)
    original = create_assignment(
        session, section=section, title="December cycle", pack_version=pack_version,
        mode="paper", due_at=DUE, late_policy="accept_late",
        late_until=DUE + timedelta(days=2), actor=instructor,
    )
    next_term = create_section(session, name="Sec 2", term="Spring 2027", actor=instructor)

    clone = clone_assignment(session, original, section=next_term,
                             shift=timedelta(days=120), actor=instructor)

    assert clone.id != original.id
    assert clone.cloned_from_id == original.id
    assert clone.title == original.title
    assert clone.mode == original.mode
    assert clone.fixed_pack_version_id == original.fixed_pack_version_id
    assert clone.due_at == DUE + timedelta(days=120)
    assert clone.late_until == original.late_until + timedelta(days=120)
    assert clone.section_id == next_term.id


def test_a_student_joins_with_the_code_and_lands_in_their_own_books(session, catalogue):
    pack_version, instructor = catalogue
    section = create_section(session, name="Sec", term="Fall 2026", actor=instructor)
    assignment = create_assignment(session, section=section, title="December",
                                   pack_version=pack_version, due_at=DUE, actor=instructor)
    student = User(email="joiner@example.edu", given_name="Ola", family_name="Okoro")
    session.add(student)
    session.flush()

    workspaces = join_with_code(session, code=section.join_code, student=student)

    assert len(workspaces) == 1
    workspace = workspaces[0]
    assert workspace.assignment_id == assignment.id
    assert workspace.variant_id is not None      # a variant is assigned on the way in
    assert session.scalars(
        select(Enrollment).where(Enrollment.section_id == section.id,
                                 Enrollment.user_id == student.id)
    ).one() is not None


def test_joining_twice_changes_nothing(session, catalogue):
    pack_version, instructor = catalogue
    section = create_section(session, name="Sec", term="Fall 2026", actor=instructor)
    create_assignment(session, section=section, title="December",
                      pack_version=pack_version, due_at=DUE, actor=instructor)
    student = User(email="twice@example.edu")
    session.add(student)
    session.flush()

    first = join_with_code(session, code=section.join_code, student=student)
    again = join_with_code(session, code=section.join_code, student=student)

    assert [w.id for w in first] == [w.id for w in again]
    assert session.execute(
        select(func.count()).select_from(Workspace).where(Workspace.student_id == student.id)
    ).scalar_one() == 1


def test_a_code_that_is_not_in_use_is_refused(session, catalogue):
    _, instructor = catalogue
    section = create_section(session, name="Sec", term="Fall 2026", actor=instructor)
    section.join_code_active = False
    session.flush()
    student = User(email="late@example.edu")
    session.add(student)
    session.flush()

    with pytest.raises(JoinRefused):
        join_with_code(session, code=section.join_code, student=student)
    with pytest.raises(JoinRefused):
        join_with_code(session, code="NOSUCHCODE", student=student)


def test_rotating_the_code_retires_the_old_one(session, catalogue):
    _, instructor = catalogue
    section = create_section(session, name="Sec", term="Fall 2026", actor=instructor)
    old = section.join_code

    rotate_join_code(session, section, actor=instructor)

    assert section.join_code != old
    student = User(email="old-code@example.edu")
    session.add(student)
    session.flush()
    with pytest.raises(JoinRefused):
        join_with_code(session, code=old, student=student)


def test_variants_are_handed_out_in_turn(session, catalogue):
    """Round robin, so a section is spread across the variants rather than left to chance."""
    pack_version, instructor = catalogue
    section = create_section(session, name="Sec", term="Fall 2026", actor=instructor)
    create_assignment(session, section=section, title="December", pack_version=pack_version,
                      due_at=DUE, variant_policy="round_robin", actor=instructor)
    variants = session.scalars(
        select(Variant.id).where(Variant.pack_version_id == pack_version.id).order_by(Variant.code)
    ).all()

    assigned = []
    for index in range(3):
        student = User(email=f"rr{index}@example.edu")
        session.add(student)
        session.flush()
        assigned.append(join_with_code(session, code=section.join_code, student=student)[0]
                        .variant_id)

    assert assigned == [variants[index % len(variants)] for index in range(3)]


def test_an_assignment_that_has_not_opened_yet_makes_no_workspace(session, catalogue):
    pack_version, instructor = catalogue
    section = create_section(session, name="Sec", term="Fall 2026", actor=instructor)
    create_assignment(session, section=section, title="Later", pack_version=pack_version,
                      due_at=DUE, opens_at=datetime.now(UTC) + timedelta(days=7), actor=instructor)
    student = User(email="early@example.edu")
    session.add(student)
    session.flush()

    workspaces = join_with_code(session, code=section.join_code, student=student)

    assert workspaces == []
    assert session.scalars(
        select(Enrollment).where(Enrollment.user_id == student.id)
    ).one() is not None  # enrolled, waiting for the assignment to open


def test_archived_assignments_are_left_alone(session, catalogue):
    pack_version, instructor = catalogue
    section = create_section(session, name="Sec", term="Fall 2026", actor=instructor)
    archived = create_assignment(session, section=section, title="Old", pack_version=pack_version,
                                 due_at=DUE, actor=instructor)
    archived.archived_at = datetime.now(UTC)
    session.flush()
    student = User(email="archived@example.edu")
    session.add(student)
    session.flush()

    assert join_with_code(session, code=section.join_code, student=student) == []
    assert session.execute(
        select(func.count()).select_from(Assignment).where(Assignment.section_id == section.id)
    ).scalar_one() == 1
    assert isinstance(section, Section)


@pytest.fixture
def pack_version(catalogue, session):
    session.commit()      # survive the view's rollback on our own, whatever order fixtures run in
    return catalogue[0]


@pytest.fixture
def instructor(catalogue, session):
    session.commit()
    return catalogue[1]


@pytest.fixture
def section(session, instructor):
    # commit() releases a savepoint (conftest: join_transaction_mode="create_savepoint"), so the
    # row survives the view's rollback before a refused re-render and is still removed at teardown.
    sec = Section(name="ACCT 1010-02", join_code="keep-join")
    session.add(sec)
    session.flush()
    # The instructor teaches it. Scoped visibility (Task 4) keeps a section you do not teach out
    # of the dropdown, and out of a form you may post -- and this test reads that dropdown back.
    session.add(SectionStaff(section_id=sec.id, user_id=instructor.id))
    session.commit()
    return sec


def _control(page: str, tag: str, attr: str, name: str, value: str) -> bool:
    """Whether the <option>/<input> named `name` with this value carries `attr`, however wrapped."""
    if tag == "option":
        block = re.search(rf'<select[^>]*name="{name}".*?</select>', page, re.S)
        assert block, f"no {name} select on the page"
        scope = block.group(0)
    else:
        scope = page
    pattern = (rf'<option[^>]*value="{re.escape(value)}"[^>]*>' if tag == "option"
               else rf'<input[^>]*name="{name}"[^>]*value="{re.escape(value)}"[^>]*>')
    found = re.search(pattern, scope)
    assert found, f"{name} has no {tag} for {value}"
    return re.search(rf'\b{attr}\b', found.group(0)) is not None


def test_a_rejected_form_keeps_every_control_the_user_set(client, session, instructor, pack_version,
                                                          section):
    """A validation error on one field must not silently reset the other fourteen.

    This is the bug that told an instructor to "Choose the company this assignment uses" about a
    company they had chosen: the error was a late cut-off, the re-render dropped the company, and
    the second submit complained about the company.
    """
    client.sign_in(instructor)

    response = client.post("/staff/assignments/new", data={
        "title": "Riverbend, section B",
        "company_policy": "fixed",
        "pack_version_id": str(pack_version.id),
        "section_choice": "existing",
        "section_id": str(section.id),
        "mode": "screen",
        "variant_policy": "manual",
        "late_policy": "accept_late",
        "due_at": "2026-12-15T17:00",
        "late_until": "2026-12-01T17:00",      # before the due date: the one real error
    })

    assert response.status_code == 422
    page = response.get_data(as_text=True)
    assert "Late work needs a cut-off after the due date" in page

    # Every control the user set must come back set.
    assert _control(page, "option", "selected", "pack_version_id", str(pack_version.id)), \
        "the company was dropped"
    assert _control(page, "option", "selected", "section_id", str(section.id)), \
        "the section was dropped"
    assert _control(page, "option", "selected", "mode", "screen"), "the documents mode was dropped"
    assert _control(page, "option", "selected", "variant_policy", "manual"), \
        "the version policy was dropped"
    assert _control(page, "option", "selected", "late_policy", "accept_late"), \
        "the late policy was dropped"
    assert _control(page, "input", "checked", "company_policy", "fixed"), \
        "the company policy radio was dropped"
    assert _control(page, "input", "checked", "section_choice", "existing"), \
        "the section choice radio was dropped"
    assert 'value="Riverbend, section B"' in page, "the title was dropped"


def test_a_rejected_choice_form_keeps_the_ticked_companies(client, session, instructor,
                                                           pack_version, section):
    """company_policy=choice with two ticked companies: the getlist branch of the template."""
    data = copy.deepcopy(testco_alpha.PACK)
    data["company"]["slug"] = "setup-second-co"
    data["company"]["name"] = "Setup Second Co"
    second = import_content(session, schema.load_pack(data), source_sha256="setup2" + "0" * 58)
    import_answer_keys(session, second, {"A": schema.load_answer_key(testco_alpha.KEY_A)})
    session.commit()
    client.sign_in(instructor)

    response = client.post("/staff/assignments/new", data={
        "title": "Riverbend, choice",
        "company_policy": "choice",
        "choice_pack_version_ids": [str(pack_version.id), str(second.id)],
        "section_choice": "existing",
        "section_id": str(section.id),
        "late_policy": "accept_late",
        "due_at": "2026-12-15T17:00",
        "late_until": "2026-12-01T17:00",
    })

    assert response.status_code == 422
    page = response.get_data(as_text=True)
    assert "Late work needs a cut-off after the due date" in page
    assert _control(page, "input", "checked", "company_policy", "choice"), \
        "the choice radio was dropped"
    assert not _control(page, "input", "checked", "company_policy", "fixed"), \
        "the fixed radio is checked as well"
    assert _control(page, "input", "checked", "choice_pack_version_ids", str(pack_version.id)), \
        "the first ticked company was dropped"
    assert _control(page, "input", "checked", "choice_pack_version_ids", str(second.id)), \
        "the second ticked company was dropped"


def test_a_rejected_form_keeps_a_new_section_the_user_was_making(client, session, instructor,
                                                                 pack_version):
    """section_choice=new: create_section runs before validation fails, then the view rolls back."""
    client.sign_in(instructor)

    response = client.post("/staff/assignments/new", data={
        "title": "Riverbend, new section",
        "company_policy": "fixed",
        "pack_version_id": str(pack_version.id),
        "section_choice": "new",
        "section_name": "ACCT 1010-77",
        "section_term": "Spring 2027",
        "late_policy": "accept_late",
        "due_at": "2026-12-15T17:00",
        "late_until": "2026-12-01T17:00",
    })

    assert response.status_code == 422
    page = response.get_data(as_text=True)
    assert "Late work needs a cut-off after the due date" in page
    assert _control(page, "input", "checked", "section_choice", "new"), \
        "the new-section radio was dropped"
    assert not _control(page, "input", "checked", "section_choice", "existing"), \
        "the existing radio is checked as well"
    assert 'value="ACCT 1010-77"' in page, "the new section's name was dropped"
    assert 'value="Spring 2027"' in page, "the new section's term was dropped"
    assert session.scalar(select(func.count()).select_from(Section)
                          .where(Section.name == "ACCT 1010-77")) == 0, \
        "a refused form must not leave its half-made section behind"
