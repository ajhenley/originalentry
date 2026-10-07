"""Two sections and the accounts around them: the world the scoping tests ask questions about.

Plain builders rather than fixtures, in the idiom of ``tests/perfect_student.py``, because the
matrix in ``tests/guards/test_scoping.py`` and the ordinary cases in
``tests/integration/test_scoped_console.py`` need the same world and a conftest does not reach
across directories.

**Everything here commits.** ``staff.assignment_create`` calls ``db.session.rollback()`` before
re-rendering a refused form, which would wipe anything created inside the test's transaction.
``tests/conftest.py`` binds the Session with ``join_transaction_mode="create_savepoint"``, so a
commit here releases a SAVEPOINT rather than the outer transaction: the rows survive the view's
rollback and the teardown rollback still removes them.

**Each builder commits for itself.** Leaning on a later builder's commit to release the savepoint
that happens to hold an earlier one's rows works only while the tests ask for them in one
particular order.
"""

from __future__ import annotations

import copy

from originalentry.models import (
    ROLE_INSTRUCTOR,
    Assignment,
    Section,
    SectionStaff,
    User,
    Variant,
    Workspace,
)
from originalentry.packs import schema
from originalentry.packs.importer import import_content
from sqlalchemy import select

from tests.packs import testco_alpha
from tests.perfect_student import build

# The reference section every company has, whatever its pack holds (student/views.py:CHART_KEY).
CHART = "chart-of-accounts"


def staff_account(session, email: str, *, role: str = ROLE_INSTRUCTOR, name: str = "Lee") -> User:
    """A staff member, brand new.

    New on purpose: Task 2's backfill attached every existing section to every staff member who
    existed when it ran, so no pre-existing account teaches nothing.
    """
    user = User(email=email, role=role, given_name=name, family_name="Teacher")
    session.add(user)
    session.commit()
    return user


def worked_world(session, teacher: User) -> dict:
    """A section ``teacher`` teaches, with one student who worked the whole cycle.

    Built through ``tests/perfect_student.build`` so every id in the returned dict is real: a 404
    on any of these routes can then only mean the scoping turned away someone it should have
    admitted. The path pieces (the journal key, the document reference, the subsidiary kind, the
    statement type) are read off the pack for the same reason -- a made-up journal key 404s on its
    own and would read as a refusal.
    """
    workspace, student, pack, key = build(
        session, testco_alpha.PACK, testco_alpha.KEY_A,
        email="scoping-worked-student@example.edu", join_code="scoping-worked",
    )
    assignment = session.get(Assignment, workspace.assignment_id)
    session.add(SectionStaff(section_id=assignment.section_id, user_id=teacher.id))
    session.commit()
    return {
        "assignment": assignment.public_id,
        "workspace": workspace.public_id,
        "company_slug": pack.company.slug,
        "section_id": assignment.section_id,
        "pack_version_id": workspace.pack_version_id,
        "student_name": f"{student.given_name} {student.family_name}",
        # Real path pieces, for the same reason the ids are real.
        "key": pack.journals[0].key,
        "ref": pack.documents[0].ref,
        "kind": pack.parties[0].kind,
        "statement_type": pack.statements[0].type,
        "section": CHART,
        "variant_code": key.variant,
    }


def _own_content_pack(session, slug: str, name: str, sha: str):
    """A copy of the fixture pack under another slug.

    Its own ContentPack each time, because ``pack_version`` is unique on (content_pack, version)
    and every one of these builders imports version 1.
    """
    pack_dict = copy.deepcopy(testco_alpha.PACK)
    pack_dict["company"]["slug"] = slug
    pack_dict["company"]["name"] = name
    pack = schema.load_pack(pack_dict)
    return pack, import_content(session, pack, source_sha256=sha)


def own_section_world(session, teacher: User) -> dict:
    """A section ``teacher`` teaches, with one assignment on it and no student work.

    The cheap half of ``worked_world``: the list and dropdown cases only need a section of this
    teacher's to be present, and a perfect student takes half a minute to build.
    """
    from originalentry.services.assignments import create_section

    _pack, pack_version = _own_content_pack(session, "scoping-own-co", "Own Co", "0" * 64)
    section = create_section(session, name="Yours, ACCT1010-01", term="Spring", actor=teacher)
    assignment = Assignment(section_id=section.id, title="Your December cycle",
                            company_policy="fixed", fixed_pack_version_id=pack_version.id)
    session.add(assignment)
    session.flush()
    session.commit()
    return {
        "assignment": assignment.public_id,
        "section_id": section.id,
        "section_name": section.name,
        "title": assignment.title,
        "pack_version_id": pack_version.id,
    }


def foreign_world(session) -> dict:
    """A real section, assignment and workspace belonging to somebody else's teacher.

    Real rows rather than invented ids: a 404 from a route whose subject does not exist proves
    nothing about scoping.
    """
    pack, pack_version = _own_content_pack(session, "scoping-foreign-co", "Foreign Co", "f" * 64)
    variant_id = session.scalars(
        select(Variant.id).where(Variant.pack_version_id == pack_version.id)
    ).first()

    teacher = User(email="scoping-foreign-teacher@example.edu", role=ROLE_INSTRUCTOR)
    student = User(email="scoping-foreign-student@example.edu",
                   given_name="Bo", family_name="Vance")
    section = Section(name="Somebody else's section", term="Spring",
                      join_code="scoping-foreign")
    session.add_all([teacher, student, section])
    session.flush()
    session.add(SectionStaff(section_id=section.id, user_id=teacher.id))
    assignment = Assignment(section_id=section.id, title="Their December cycle",
                            company_policy="fixed", fixed_pack_version_id=pack_version.id)
    session.add(assignment)
    session.flush()
    workspace = Workspace(assignment_id=assignment.id, student_id=student.id,
                          pack_version_id=pack_version.id, variant_id=variant_id,
                          status="in_progress")
    session.add(workspace)
    session.commit()
    return {
        "assignment": assignment.public_id,
        "workspace": workspace.public_id,
        "company_slug": pack.company.slug,
        "section_id": section.id,
        "pack_version_id": pack_version.id,
        "teacher_id": teacher.id,
    }
