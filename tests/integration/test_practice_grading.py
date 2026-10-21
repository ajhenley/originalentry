"""Grading one practice copy, and reading the marks it produced.

The last thing a teacher needs from their own copy: a mark, and the marks screen read *before*
the class's marks are released. Four claims, each of which fails silently without its own test.

* **The copy is gradable on its own.** ``grade_section`` skips practice copies through the
  chokepoint, so a cohort run never produces a ``GradeRun`` for one -- which means without a
  per-copy action a teacher's copy can never be graded at all. ``staff.practice_grade`` grades
  exactly one workspace: the signed-in teacher's own.
* **The marks screen does not wait for release.** ``student.views.marks`` gates on
  ``assignment.marks_released_at``, and the spec's reason for the practice copy ignoring it is
  the whole point of this task: "the marks screen is the one screen they most need to read
  before releasing marks to a class".
* **And it still waits for everybody else.** A gate relaxed one line too wide shows a section its
  marks early, and nothing else on this branch would notice. Two tests hold that line: an
  ordinary student's screen, and an account that owns a flagged row but is not staff.
* **A student's work is not reachable through this route.** The cohort path is how a student's
  books get graded, with its own scoping. This route takes no workspace id at all -- it grades
  what ``practice_copy`` returns for the caller -- so another teacher's copy and a student's
  workspace are both unreachable by construction, and ``abort(404)`` says nothing either way.

Every fixture creates everything it later asserts on, and commits. The suite runs against a
shared development branch holding rows from earlier manual testing, so a fixture leaning on an
empty table -- or on a row it did not create -- would be accidentally sighted rather than blind.
The commit is load-bearing for a second reason: this route rolls nothing back, but
``test_practice_screens`` has already paid for a flush-only world, where the first view rollback
took the signed-in user with it and every later request answered 302 to sign-in.
"""

from __future__ import annotations

import html
import re

import pytest
from originalentry.grading.workspace import grade_workspace
from originalentry.models import (
    ROLE_INSTRUCTOR,
    ROLE_STUDENT,
    ContentPack,
    GradeRun,
    PackVersion,
    Section,
    SectionStaff,
    User,
    Variant,
    Workspace,
)
from originalentry.packs import schema
from originalentry.packs.importer import import_answer_keys, import_content
from originalentry.services.assignments import create_assignment
from originalentry.services.grades import grade_section, record_run, release_marks
from originalentry.services.practice import open_practice
from sqlalchemy import func, select

from tests.packs import testco_alpha

pytestmark = pytest.mark.db


# ── the world ──────────────────────────────────────────────────────────────────────────

def _user(email: str, *, role: str | None = None, family_name: str = "Sowande") -> User:
    user = User(email=email, given_name="Ada", family_name=family_name)
    if role is not None:
        user.role = role
    return user


@pytest.fixture
def world(session):
    """One assignment with one student's books, and two teachers who both teach the section.

    ``other_teacher`` holds a ``SectionStaff`` row on the *same* section deliberately: a refusal
    that came from ``_assignment_or_404`` would prove only that scoping works, which another
    suite already holds. Teaching the section is what makes the refusal in the grading tests
    below about ownership and nothing else.

    No practice copy here: the ``copy`` fixture builds one through ``open_practice``, so these
    tests assert on the shape the service really makes.
    """
    pack_version = import_content(session, schema.load_pack(testco_alpha.PACK),
                                  source_sha256="grd" + "1" * 61)
    import_answer_keys(session, pack_version,
                       {"A": schema.load_answer_key(testco_alpha.KEY_A)})
    variant_id = session.scalars(
        select(Variant.id).where(Variant.pack_version_id == pack_version.id)).first()

    section = Section(name="Sec", join_code="grading-join")
    teacher = _user("grading-teacher@example.edu", role=ROLE_INSTRUCTOR,
                    family_name="Teacherson")
    other_teacher = _user("grading-other-teacher@example.edu", role=ROLE_INSTRUCTOR,
                          family_name="Cotelli")
    student = _user("grading-student@example.edu", family_name="Studentson")
    # The account that owns a flagged row it should never have been given -- see the test that
    # uses it. A second student, so that row needs nothing deleted to fit beside the first one's:
    # uq_workspace_assignment_student_live allows one live workspace per (assignment, student).
    second_student = _user("grading-second-student@example.edu", family_name="Secondson")
    session.add_all([section, teacher, other_teacher, student, second_student])
    session.flush()
    session.add_all([
        SectionStaff(section_id=section.id, user_id=teacher.id),
        SectionStaff(section_id=section.id, user_id=other_teacher.id),
    ])
    assignment = create_assignment(session, section=section, title="December",
                                   pack_version=pack_version)
    student_workspace = Workspace(assignment_id=assignment.id, student_id=student.id,
                                  pack_version_id=pack_version.id, variant_id=variant_id,
                                  status="in_progress")
    session.add(student_workspace)
    session.flush()
    session.commit()
    version = session.get(PackVersion, pack_version.id)
    return {
        "section": section, "assignment": assignment, "teacher": teacher,
        "other_teacher": other_teacher, "student": student, "second_student": second_student,
        "student_workspace": student_workspace, "pack_version": pack_version,
        "variant_id": variant_id,
        "slug": session.get(ContentPack, version.content_pack_id).slug,
    }


@pytest.fixture
def copy(session, world):
    """The teacher's live practice copy, made the way the service makes one."""
    made = open_practice(session, world["assignment"], world["teacher"])
    session.commit()
    return made


# ── helpers ────────────────────────────────────────────────────────────────────────────

def _text(response) -> str:
    """The visible text, so an assertion is about the page rather than about its markup."""
    return html.unescape(
        re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", response.get_data(as_text=True))))


def _grade_url(assignment) -> str:
    return f"/staff/progress/{assignment.public_id}/practice/grade"


def _marks_url(workspace, slug: str) -> str:
    return f"/w/{workspace.public_id}/{slug}/marks"


def _runs(session, workspace) -> int:
    return session.execute(
        select(func.count()).select_from(GradeRun)
        .where(GradeRun.workspace_id == workspace.id)
    ).scalar_one()


def _component_labels(body: str) -> list[str]:
    """The row headings of the marks table -- the evidence, as the screen shows it."""
    return sorted({
        found.strip()
        for found in re.findall(r'<th scope="row" class="text-left font-normal">([^<]+)', body)
        if found.strip()
    })


# ── grading the copy ───────────────────────────────────────────────────────────────────

def test_a_teacher_can_grade_their_own_practice_copy(client, session, world, copy):
    """The whole of the action: one workspace, the caller's own, and a run stored for it.

    The cohort run can never produce one -- the chokepoint excludes the copy -- so without this
    route a practice copy has no mark at all, and the marks screen below has nothing to read.
    """
    client.sign_in(world["teacher"])
    assert _runs(session, copy) == 0, "the copy was graded before anybody asked"

    posted = client.post(_grade_url(world["assignment"]))

    assert posted.status_code == 302, _text(posted)
    assert "sign-in" not in posted.headers["Location"], \
        "the request never reached the route: the session was rolled back under it"
    assert posted.headers["Location"].endswith(_marks_url(copy, world["slug"])), \
        f"graded, but landed at {posted.headers['Location']} rather than on the marks screen"
    assert _runs(session, copy) == 1


def test_a_cohort_run_still_skips_the_copy_it_has_graded(client, session, world, copy):
    """Verified rather than assumed, in the state this task is the only thing that creates.

    ``grade_section`` goes through the chokepoint, so it should skip a practice copy whether or
    not one already has a run of its own -- and a run of its own is new here. A cohort run that
    picked the copy up would put a teacher's attempts in the class's grading records, which is
    this project's first anti-goal.
    """
    client.sign_in(world["teacher"])
    client.post(_grade_url(world["assignment"]))

    graded, total, _ = grade_section(session, world["assignment"], actor=world["teacher"])

    assert [run.workspace_id for run in graded] == [world["student_workspace"].id]
    assert total == 1, "the cohort run counted the practice copy as one of the section's books"
    assert _runs(session, copy) == 1, "the cohort run graded the practice copy a second time"


# ── the marks screen, before the class's marks are released ────────────────────────────

def test_the_marks_screen_shows_the_mark_without_marks_being_released(
        client, session, world, copy):
    """student/views.py's marks screen gates on assignment.marks_released_at. The marks screen is
    the one screen a teacher most needs to read BEFORE releasing marks to a class."""
    client.sign_in(world["teacher"])
    assert world["assignment"].marks_released_at is None, "the fixture released the marks itself"

    before = client.get(_marks_url(copy, world["slug"]))
    client.post(_grade_url(world["assignment"]))
    after = client.get(_marks_url(copy, world["slug"]))

    # Ungraded, the screen says so. "Not released yet" would be a false sentence on the one
    # screen whose release gate does not apply to this reader.
    assert before.status_code == 200
    assert "not graded this copy yet" in _text(before)
    assert "not been released" not in _text(before)
    assert after.status_code == 200
    assert "Marks awarded" in _text(after), "the mark was withheld from the teacher who made it"
    assert "Document triage" in _text(after)
    session.refresh(world["assignment"])
    assert world["assignment"].marks_released_at is None, \
        "reading the mark released the whole section's marks"


def test_a_students_marks_screen_still_waits_for_release(client, session, world):
    """Guards the exemption: it must not relax the gate for anyone else."""
    student_workspace = world["student_workspace"]
    record_run(session, student_workspace, grade_workspace(session, student_workspace))
    session.commit()
    client.sign_in(world["student"])

    read = client.get(_marks_url(student_workspace, world["slug"]))

    assert read.status_code == 200
    assert "not been released" in _text(read)
    assert "Marks awarded" not in _text(read), "a student read their marks before release"
    assert not _component_labels(read.get_data(as_text=True))


def test_an_owner_who_is_not_staff_waits_for_release_like_anybody_else(client, session, world):
    """``is_own_practice`` carries no role check, deliberately -- so the exemption asks for one,
    exactly as ``services.write._check_gates`` does where it grants the deadline skip.

    The row below is the one ``services.practice`` refuses to create and nothing else can: a
    flagged workspace whose owner is a student. Without the role check, holding one would be a
    way to read a mark before the section's marks are released.
    """
    owner = world["second_student"]
    flagged = Workspace(assignment_id=world["assignment"].id, student_id=owner.id,
                        staff_practice=True, pack_version_id=world["pack_version"].id,
                        variant_id=world["variant_id"], status="in_progress")
    session.add(flagged)
    session.flush()
    record_run(session, flagged, grade_workspace(session, flagged))
    session.commit()
    assert owner.role == ROLE_STUDENT
    client.sign_in(owner)

    read = client.get(_marks_url(flagged, world["slug"]))

    assert read.status_code == 200, "the owner could not reach their own workspace at all"
    assert "not been released" in _text(read)
    assert "Marks awarded" not in _text(read), \
        "an account that is not staff read a mark before the section's marks were released"


def test_the_evidence_reads_as_a_students_would(client, session, world, copy):
    """Which is the point of there being no second code path: the copy is a real workspace, and
    the marks screen is the student's screen. Component for component, the same table."""
    client.sign_in(world["teacher"])
    client.post(_grade_url(world["assignment"]))
    teacher_sees = client.get(_marks_url(copy, world["slug"]))

    student_workspace = world["student_workspace"]
    record_run(session, student_workspace, grade_workspace(session, student_workspace))
    release_marks(session, world["assignment"])
    session.commit()
    client.sign_in(world["student"])
    student_sees = client.get(_marks_url(student_workspace, world["slug"]))

    assert teacher_sees.status_code == 200 and student_sees.status_code == 200
    theirs = _component_labels(student_sees.get_data(as_text=True))
    assert theirs, "the student's own released marks screen listed no components to compare with"
    assert _component_labels(teacher_sees.get_data(as_text=True)) == theirs


# ── whose copy it grades, and whose it cannot ──────────────────────────────────────────

def test_a_teacher_cannot_grade_another_teachers_practice_copy(client, session, world, copy):
    """Owner-only, and 404 rather than 403: a refusal that said "not yours" would confirm the
    copy exists. ``other_teacher`` teaches this section, so scoping admits them and ownership is
    the only thing refusing."""
    client.sign_in(world["other_teacher"])

    posted = client.post(_grade_url(world["assignment"]))

    assert posted.status_code == 404
    assert _runs(session, copy) == 0, "a colleague graded a teacher's practice copy"
    assert session.scalars(
        select(Workspace).where(Workspace.student_id == world["other_teacher"].id)
    ).all() == [], "the route opened a copy of its own rather than refusing"


def test_a_teacher_cannot_grade_a_students_workspace_through_this_route(
        client, session, world, copy):
    """The cohort path is how a student's work gets graded, with its own scoping.

    The route takes no workspace id, so one named in the form is not a workspace it can reach.
    A practice copy exists here on purpose: the route runs and succeeds, and the thing being
    asserted is *which* workspace it graded.
    """
    student_workspace = world["student_workspace"]
    client.sign_in(world["teacher"])

    posted = client.post(_grade_url(world["assignment"]),
                         data={"workspace": student_workspace.public_id})

    assert posted.status_code == 302, _text(posted)
    assert _runs(session, copy) == 1
    assert _runs(session, student_workspace) == 0, \
        "a student's books were graded through the practice route"
