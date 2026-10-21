"""Assigning a chapter, and a console that makes sense for one.

Without this half the feature is unusable by the instructors it is for: a chapter can be imported
and nothing can be assigned from it. Two things carry real risk.

``problems_required`` has to be refused when it is wrong, loudly, at creation. A runtime fallback
would rescale every mark in the section against a denominator nobody chose, and nothing on any
screen would say so.

And the console's practice-set furniture has to go. Diagnostics' triage tally would report every
problem "not handled" for every student -- the answer key carries triage values only because V10
demands them -- which reads as a cohort in trouble rather than a column that does not apply.
"""

from __future__ import annotations

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
from originalentry.problems import importing
from originalentry.services.problems import submit
from sqlalchemy import select

from tests.packs import testco_alpha
from tests.unit.test_chapter_file import VALID

pytestmark = pytest.mark.db

RIGHT = {
    "line-1-account": "150", "line-1-debit": "4800.00", "line-1-credit": "",
    "line-2-account": "101", "line-2-debit": "", "line-2-credit": "1800.00",
    "line-3-account": "201", "line-3-debit": "", "line-3-credit": "3000.00",
}


@pytest.fixture
def teacher(session, client):
    user = User(email="prof@example.edu", given_name="Lee", family_name="Osei", role="instructor")
    session.add(user)
    session.flush()
    client.sign_in(user)
    return user


@pytest.fixture
def section(session, teacher):
    row = Section(name="ACCT 101", join_code="psa-join")
    session.add(row)
    session.flush()
    session.add(SectionStaff(section_id=row.id, user_id=teacher.id))
    session.flush()
    return row


@pytest.fixture
def chapter_version(session):
    return importing.import_chapter(session, VALID)


@pytest.fixture
def practice_version(session):
    version = import_content(session, schema.load_pack(testco_alpha.PACK),
                             source_sha256="psa" + "0" * 61)
    import_answer_keys(session, version, {"A": schema.load_answer_key(testco_alpha.KEY_A)})
    return version


def _create(client, section, version, **extra):
    return client.post("/staff/assignments/new", data={
        "title": "Chapter 3", "section_choice": "existing", "section_id": str(section.id),
        "company_policy": "fixed", "pack_version_id": str(version.id),
        "mode": "screen", "late_policy": "closed", **extra,
    })


def _assignment(session, section):
    return session.scalars(
        select(Assignment).where(Assignment.section_id == section.id)).one_or_none()


# ── creating one ───────────────────────────────────────────────────────────────────────

def test_a_problem_set_assignment_records_how_many_count(client, session, section,
                                                         chapter_version):
    response = _create(client, section, chapter_version, problems_required="2")

    assert response.status_code in (302, 303), response.get_data(as_text=True)[:400]
    assert _assignment(session, section).problems_required == 2


def test_problems_required_larger_than_the_chapter_is_refused(client, session, section,
                                                              chapter_version):
    """Review Focus 2. A 422 naming the problem count, not a runtime fallback: a silent default
    rescales every mark in the section and nothing on screen says so."""
    response = _create(client, section, chapter_version, problems_required="9")

    assert response.status_code == 422
    body = response.get_data(as_text=True)
    assert "2" in body, "the error does not say how many problems the chapter has"
    assert _assignment(session, section) is None


def test_problems_required_of_zero_is_refused(client, session, section, chapter_version):
    response = _create(client, section, chapter_version, problems_required="0")

    assert response.status_code == 422
    assert _assignment(session, section) is None


def test_problems_required_absent_is_refused_for_a_problem_set(client, session, section,
                                                               chapter_version):
    """The component grades out of every problem and flags for review when this is missing. That
    is a safety net for a mistake, not a way to create an assignment."""
    response = _create(client, section, chapter_version)

    assert response.status_code == 422
    assert _assignment(session, section) is None


def test_problems_required_that_is_not_a_number_is_refused(client, session, section,
                                                           chapter_version):
    response = _create(client, section, chapter_version, problems_required="six")

    assert response.status_code == 422
    assert _assignment(session, section) is None


def test_a_refused_form_keeps_what_was_typed(client, session, section, chapter_version):
    """An instructor who mistypes one field should not retype the other six."""
    response = _create(client, section, chapter_version, problems_required="9",
                       title="Chapter three, week two")

    assert "Chapter three, week two" in response.get_data(as_text=True)


def test_a_practice_set_assignment_still_needs_no_problems_required(client, session, section,
                                                                    practice_version):
    """The field is null for every practice set and nothing about them changes."""
    response = _create(client, section, practice_version)

    assert response.status_code in (302, 303)
    assert _assignment(session, section).problems_required is None


def test_a_problem_set_cannot_be_offered_as_a_choice(client, session, section, chapter_version,
                                                     practice_version):
    """One assignment, one count. A choice between chapters of different lengths would mark two
    students against different denominators under one `problems_required`."""
    response = client.post("/staff/assignments/new", data={
        "title": "Pick one", "section_choice": "existing", "section_id": str(section.id),
        "company_policy": "choice",
        "choice_pack_version_ids": [str(chapter_version.id), str(practice_version.id)],
        "mode": "screen", "late_policy": "closed", "problems_required": "2",
    })

    assert response.status_code == 422
    assert _assignment(session, section) is None


# ── the form offers the chapter ────────────────────────────────────────────────────────

def test_the_new_assignment_form_offers_the_chapter(client, section, chapter_version):
    body = client.get("/staff/assignments/new").get_data(as_text=True)

    assert "Analyzing and Recording Transactions" in body
    assert "problems_required" in body, "the form has nowhere to say how many count"


def test_the_form_says_how_many_problems_each_chapter_has(client, section, chapter_version):
    """An instructor setting the count needs to know the ceiling before they are refused."""
    body = client.get("/staff/assignments/new").get_data(as_text=True)

    assert "2 problems" in body


# ── the console ────────────────────────────────────────────────────────────────────────

@pytest.fixture
def assigned(session, section, chapter_version, teacher):
    student = User(email="stu@example.edu", given_name="Ada", family_name="Sowande")
    session.add(student)
    session.flush()
    session.add(Enrollment(section_id=section.id, user_id=student.id))
    assignment = Assignment(section_id=section.id, title="Chapter 3", company_policy="fixed",
                            fixed_pack_version_id=chapter_version.id, problems_required=2)
    session.add(assignment)
    session.flush()
    variant_id = session.scalars(
        select(Variant.id).where(Variant.pack_version_id == chapter_version.id)).one()
    ws = Workspace(assignment_id=assignment.id, student_id=student.id,
                   pack_version_id=chapter_version.id, variant_id=variant_id,
                   status="in_progress")
    session.add(ws)
    session.flush()
    submit(session, ws, "P3-01", RIGHT)
    session.flush()
    return assignment, ws, student


def test_diagnostics_hides_the_triage_tally_for_a_problem_set(client, session, assigned):
    """It would report every problem "not handled" for every student, because the key carries
    triage values only to satisfy V10."""
    assignment, _ws, _student = assigned

    body = client.get(f"/staff/diagnostics/{assignment.public_id}").get_data(as_text=True)

    assert body != ""
    assert "Documents handled differently from the key" not in body


def test_diagnostics_still_works_for_a_problem_set(client, session, assigned):
    """Guards the test above from the inside: hiding the whole page would also pass it."""
    assignment, _ws, _student = assigned

    response = client.get(f"/staff/diagnostics/{assignment.public_id}")

    assert response.status_code == 200
    assert "Chapter 3" in response.get_data(as_text=True)


def test_progress_does_not_offer_practice_set_columns(client, session, assigned):
    """The ladder's later stages -- Posted, Statements, Closed -- have no meaning here, and
    neither do a triaged-documents count or a posted-journals count."""
    assignment, _ws, _student = assigned

    body = client.get(f"/staff/progress/{assignment.public_id}").get_data(as_text=True)

    assert "Journals posted" not in body
    assert "Problems worked" in body


def test_the_stage_ladder_ends_at_journalising_for_a_problem_set(client, session, assigned):
    """Posted, Statements and Closed have no meaning here: a problem set has nothing to post and
    no statements to build, so a student who has recorded an entry is as far along as the ladder
    goes. Asserted rather than assumed -- it is true because nothing posts, which is the kind of
    fact that stops being true when somebody adds a posting step."""
    from originalentry.services.progress import assignment_progress

    assignment, _ws, _student = assigned

    stages = {row.stage for row in assignment_progress(session, assignment)}

    assert stages
    for beyond in ("Posted", "Statements", "Closed", "Adjusting"):
        assert beyond not in stages, f"a problem set reached {beyond!r}"


def test_progress_counts_the_problems_a_student_has_worked(client, session, assigned):
    """The column that replaces the triaged-documents count."""
    from originalentry.services.progress import assignment_progress

    assignment, _ws, _student = assigned

    row = assignment_progress(session, assignment)[0]

    assert row.problems_worked == 1
    assert row.problems_total == 2


def test_progress_still_names_each_student(client, session, assigned):
    assignment, _ws, _student = assigned

    body = client.get(f"/staff/progress/{assignment.public_id}").get_data(as_text=True)

    assert "Ada" in body or "Sowande" in body


def test_a_practice_set_console_is_unchanged(client, session, section, practice_version,
                                             teacher):
    """The anti-goal for this task: a practice set's console must look exactly as it did."""
    assignment = Assignment(section_id=section.id, title="December", company_policy="fixed",
                            fixed_pack_version_id=practice_version.id)
    session.add(assignment)
    session.flush()
    # A student with a workspace, or progress renders "Nobody has been enrolled" and the column
    # assertions below would pass against a page that has no table at all.
    student = User(email="prac@example.edu", given_name="Bo", family_name="Adeyemi")
    session.add(student)
    session.flush()
    session.add(Enrollment(section_id=section.id, user_id=student.id))
    variant_id = session.scalars(
        select(Variant.id).where(Variant.pack_version_id == practice_version.id)).first()
    session.add(Workspace(assignment_id=assignment.id, student_id=student.id,
                          pack_version_id=practice_version.id, variant_id=variant_id,
                          status="in_progress"))
    session.flush()

    progress = client.get(f"/staff/progress/{assignment.public_id}").get_data(as_text=True)
    diagnostics = client.get(f"/staff/diagnostics/{assignment.public_id}").get_data(as_text=True)

    assert "Journals posted" in progress
    assert "Problems worked" not in progress
    assert "Documents handled differently from the key" in diagnostics


# ── the spec's fifth goal ──────────────────────────────────────────────────────────────

def test_a_problem_set_s_marks_reach_the_csv_and_the_mastery_view(client, session, assigned):
    """The spec's fifth goal, and the whole reason a problem set is a pack: it says the CSV and
    the mastery view "need no change", which is a claim and not a fact until something asserts
    it."""
    from originalentry.services.grades import grade_section

    assignment, ws, _student = assigned
    # Block A is deliberately submitted-only (services/mastery.py: a rate computed over students
    # still working would move every time somebody saved), so the work has to be handed in before
    # the mastery view has anything to say -- which is also when an instructor looks at it.
    ws.status = "submitted"
    session.flush()
    grade_section(session, assignment, actor=None)
    session.flush()

    csv_body = client.get(
        f"/staff/grading/{assignment.public_id}/marks.csv").get_data(as_text=True)
    diagnostics = client.get(
        f"/staff/diagnostics/{assignment.public_id}").get_data(as_text=True)

    assert "Sowande" in csv_body, "the student is missing from the marks export"
    assert "Debit/credit" in diagnostics, (
        "the chapter's concept does not appear in the mastery view, so problems_best_n's tag is "
        "not reaching it"
    )


# ── the other two creation paths ───────────────────────────────────────────────────────

def test_cloning_a_problem_set_assignment_keeps_how_many_count(client, session, assigned):
    """Cloning last term's assignment is a creation path, and it bypassed assignment_create's
    validation entirely: the clone carried NULL, which lands in problems_best_n's
    every-problem-counts branch. That is the "silent fallback rescales a whole section" the spec
    forbids, reached from a button in the console.
    """
    from datetime import timedelta

    from originalentry.services.assignments import clone_assignment

    assignment, _ws, _student = assigned
    assert assignment.problems_required == 2

    clone = clone_assignment(session, assignment, shift=timedelta(days=7), actor=None)

    assert clone.problems_required == 2


def test_the_console_clone_action_keeps_how_many_count(client, session, assigned):
    """The same thing through the route an instructor actually presses."""
    assignment, _ws, _student = assigned

    client.post(f"/staff/assignments/{assignment.public_id}/clone", data={"shift_days": "7"})

    clone = session.scalars(
        select(Assignment).where(Assignment.cloned_from_id == assignment.id)).one()
    assert clone.problems_required == 2


def test_migrating_to_a_shorter_chapter_is_refused(client, session, section, teacher):
    """problems_required is validated at creation against the chapter's length, and migrating to a
    newer version with fewer problems left it above the ceiling: ranked[:required] shortens while
    the denominator does not, so the whole section is marked out of a total it cannot reach.
    Same spec sentence as the clone, a different entry point.
    """
    from originalentry.packs.migrate import MigrationRefused, migrate_assignment
    from originalentry.problems import importing as chapter_importing

    first = chapter_importing.import_chapter(session, VALID)
    assignment = Assignment(section_id=section.id, title="Chapter 3", company_policy="fixed",
                            fixed_pack_version_id=first.id, problems_required=2)
    session.add(assignment)
    session.flush()

    # A corrected chapter with one problem instead of two.
    shorter = VALID[:VALID.index("  - ref: P3-02")] + "\n"
    second = chapter_importing.import_chapter(session, shorter)
    assert len(second.manifest["documents"]) == 1

    with pytest.raises(MigrationRefused) as refused:
        migrate_assignment(session, assignment, second.version, dry_run=True)

    assert "problems" in str(refused.value).lower()


def test_migrating_to_a_chapter_that_is_long_enough_is_allowed(client, session, section, teacher):
    """Guards the refusal from the inside: refusing every migration would also pass it."""
    from originalentry.packs.migrate import migrate_assignment
    from originalentry.problems import importing as chapter_importing

    first = chapter_importing.import_chapter(session, VALID)
    assignment = Assignment(section_id=section.id, title="Chapter 3", company_policy="fixed",
                            fixed_pack_version_id=first.id, problems_required=2)
    session.add(assignment)
    session.flush()
    second = chapter_importing.import_chapter(
        session, VALID.replace("agreeing to pay the rest later.", "agreeing to pay the balance."))

    report = migrate_assignment(session, assignment, second.version, dry_run=True)

    assert report is not None


# ── a chapter has one variant, so "I will assign them" is meaningless ──────────────────

def test_a_problem_set_assignment_cannot_use_manual_variants(client, session, section,
                                                             chapter_version):
    """A chapter pack has exactly one variant, so "I will assign them" hands out nothing:
    variant_for returns None, the workspace gets variant_id NULL, no answer key matches, and the
    problem screen then has no key to compare against. Refused at creation rather than guarded in
    five places downstream.
    """
    response = _create(client, section, chapter_version, problems_required="2",
                       variant_policy="manual")

    assert response.status_code == 422
    assert _assignment(session, section) is None


def test_a_practice_set_assignment_may_still_use_manual_variants(client, session, section,
                                                                 practice_version):
    """The policy exists for a reason and multi-variant practice sets keep it."""
    response = _create(client, section, practice_version, variant_policy="manual")

    assert response.status_code in (302, 303)
    assert _assignment(session, section).variant_policy == "manual"
