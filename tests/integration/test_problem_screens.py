"""What a student sees on a chapter problem, and when.

The progressive design is the feature. Attempt one says what kind of thing is wrong and withholds
which line, so a student has to look at their own work; attempt two shows the lines and the pack's
own sentence about the misconception; only the button reaches the answer. Each of those is a thing
the page must *not* say yet, which is why these tests assert absence as much as presence.
"""

from __future__ import annotations

import re

import pytest
from originalentry.models import Assignment, Section, User, Variant, Workspace
from originalentry.problems import importing
from sqlalchemy import select

from tests.unit.test_chapter_file import VALID

pytestmark = pytest.mark.db

RIGHT = {
    "line-1-account": "150", "line-1-debit": "4800.00", "line-1-credit": "",
    "line-2-account": "101", "line-2-debit": "", "line-2-credit": "1800.00",
    "line-3-account": "201", "line-3-debit": "", "line-3-credit": "3000.00",
}
#: Balanced, and the wrong account for the thing bought -- which is the pack's own signature.
WRONG_ACCOUNT = {**RIGHT, "line-1-account": "140"}
#: Unbalanced: refused, and it must cost nothing.
TYPO = {**RIGHT, "line-2-credit": "180.00"}


@pytest.fixture
def world(session):
    version = importing.import_chapter(session, VALID)
    student = User(email="screens@example.edu", given_name="Ada", family_name="Sowande")
    section = Section(name="Sec", join_code="scr-join")
    session.add_all([student, section])
    session.flush()
    assignment = Assignment(section_id=section.id, title="Chapter 3", company_policy="fixed",
                            fixed_pack_version_id=version.id, problems_required=2)
    session.add(assignment)
    session.flush()
    variant_id = session.scalars(
        select(Variant.id).where(Variant.pack_version_id == version.id)).one()
    ws = Workspace(assignment_id=assignment.id, student_id=student.id,
                   pack_version_id=version.id, variant_id=variant_id, status="in_progress")
    session.add(ws)
    session.flush()
    from originalentry.extensions import db
    from originalentry.models import ContentPack, PackVersion
    slug = db.session.get(
        ContentPack, db.session.get(PackVersion, version.id).content_pack_id).slug
    return ws, student, slug, assignment


def _list_url(ws, slug):
    return f"/w/{ws.public_id}/{slug}/problems"


def _url(ws, slug, ref):
    return f"/w/{ws.public_id}/{slug}/problems/{ref}"


def _text(response) -> str:
    """Visible text only: class names and aria labels are not what a student reads."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", response.get_data(as_text=True)))


def _post(client, ws, slug, ref, form):
    return client.post(_url(ws, slug, ref), data=form)


# ── the list ───────────────────────────────────────────────────────────────────────────

def test_the_list_shows_every_problem_and_how_many_count(client, world):
    ws, student, slug, _assignment = world
    client.sign_in(student)

    text = _text(client.get(_list_url(ws, slug)))

    assert "P3-01" in text and "P3-02" in text
    assert "best 2" in text, "the list does not say how many problems count"
    assert "Not started" in text


def test_the_list_shows_no_running_mark(client, world):
    """A student sees nothing about marks until the instructor releases them, and a problem set is
    not the exception -- which is also why "best 2 of these 2" is a count and not a score.

    The navigation's own Marks link is not a mark; it leads to the page that is gated on
    ``Assignment.marks_released_at``. So this asserts against a *figure*, not a word.
    """
    ws, student, slug, _assignment = world
    client.sign_in(student)
    _post(client, ws, slug, "P3-01", RIGHT)

    text = _text(client.get(_list_url(ws, slug)))

    assert "%" not in text
    for phrase in ("out of", "score", "earned", "so far:"):
        assert phrase not in text.lower(), f"the list reads like a running mark: {phrase!r}"


def test_the_list_offers_no_link_a_problem_set_cannot_follow(client, world):
    """The fence 404s journals, ledgers, statements, the trial balance and the print record, so
    offering those links would be offering a dead end on every page."""
    ws, student, slug, _assignment = world
    client.sign_in(student)

    text = _text(client.get(_list_url(ws, slug)))

    for label in ("Documents", "Journals", "Trial balance", "Ledgers", "Statements",
                  "Checkpoints", "Print"):
        assert label not in text, f"the navigation offers {label!r}, which 404s here"
    assert "Problems" in text


def test_the_list_tracks_each_problem_s_state(client, world):
    ws, student, slug, _assignment = world
    client.sign_in(student)
    _post(client, ws, slug, "P3-01", RIGHT)
    _post(client, ws, slug, "P3-02", WRONG_ACCOUNT)
    _post(client, ws, slug, "P3-02", WRONG_ACCOUNT)

    text = _text(client.get(_list_url(ws, slug)))

    assert "Matches the expected entry" in text
    assert "2 attempts so far" in text


# ── level 1: the shape, and nothing more ───────────────────────────────────────────────

def test_the_first_attempt_does_not_say_which_line_is_wrong(client, world):
    """The whole of the progressive design."""
    ws, student, slug, _assignment = world
    client.sign_in(student)
    _post(client, ws, slug, "P3-01", WRONG_ACCOUNT)

    text = _text(client.get(_url(ws, slug, "P3-01")))

    assert "Your entry, line by line" not in text, "the per-line table appeared at level 1"
    assert "One thing to look at" not in text, "the signature appeared at level 1"
    assert "The entry this transaction calls for" not in text, "the answer appeared at level 1"


def test_the_first_attempt_does_say_what_kind_of_thing_is_wrong(client, world):
    """Guards the test above from the inside: withholding everything is not the design."""
    ws, student, slug, _assignment = world
    client.sign_in(student)
    _post(client, ws, slug, "P3-01", WRONG_ACCOUNT)

    text = _text(client.get(_url(ws, slug, "P3-01")))

    assert "not one this transaction touches" in text


# ── level 2: the lines and the signature ───────────────────────────────────────────────

def test_the_second_attempt_shows_the_lines(client, world):
    ws, student, slug, _assignment = world
    client.sign_in(student)
    _post(client, ws, slug, "P3-01", WRONG_ACCOUNT)
    _post(client, ws, slug, "P3-01", WRONG_ACCOUNT)

    text = _text(client.get(_url(ws, slug, "P3-01")))

    assert "Your entry, line by line" in text


def test_the_second_attempt_shows_the_pack_s_own_sentence(client, world):
    """T8.8 is exempted here and only here: the sentence is prose the chapter's author wrote about
    a misconception, which is what makes the problem self-grading."""
    ws, student, slug, _assignment = world
    client.sign_in(student)
    _post(client, ws, slug, "P3-01", WRONG_ACCOUNT)
    _post(client, ws, slug, "P3-01", WRONG_ACCOUNT)

    text = _text(client.get(_url(ws, slug, "P3-01")))

    assert "recorded as supplies" in text, "the signature's label did not reach the student"


def test_the_second_attempt_still_does_not_show_the_answer(client, world):
    ws, student, slug, _assignment = world
    client.sign_in(student)
    for _ in range(5):
        _post(client, ws, slug, "P3-01", WRONG_ACCOUNT)

    text = _text(client.get(_url(ws, slug, "P3-01")))

    assert "The entry this transaction calls for" not in text


# ── level 3: only the button ───────────────────────────────────────────────────────────

def test_the_answer_appears_only_after_the_reveal_button(client, world):
    ws, student, slug, _assignment = world
    client.sign_in(student)

    before = _text(client.get(_url(ws, slug, "P3-01")))
    client.post(_url(ws, slug, "P3-01") + "/answer")
    after = _text(client.get(_url(ws, slug, "P3-01")))

    assert "The entry this transaction calls for" not in before
    assert "The entry this transaction calls for" in after
    assert "no longer counts toward your mark" in after


def test_the_reveal_button_is_gone_once_it_has_been_used(client, world):
    ws, student, slug, _assignment = world
    client.sign_in(student)
    client.post(_url(ws, slug, "P3-01") + "/answer")

    text = _text(client.get(_url(ws, slug, "P3-01")))

    assert "Show me this entry" not in text


def test_revealing_one_problem_does_not_reveal_another(client, world):
    ws, student, slug, _assignment = world
    client.sign_in(student)
    client.post(_url(ws, slug, "P3-01") + "/answer")

    text = _text(client.get(_url(ws, slug, "P3-02")))

    assert "The entry this transaction calls for" not in text


# ── a refusal costs nothing, on the screen too ─────────────────────────────────────────

def test_a_refused_submission_says_so_and_does_not_advance_the_disclosure(client, world):
    ws, student, slug, _assignment = world
    client.sign_in(student)

    response = _post(client, ws, slug, "P3-01", TYPO)

    assert response.status_code == 422
    text = _text(response)
    assert "was not recorded" in text
    assert "Your entry, line by line" not in text, "a typo unlocked the per-line table"


def test_two_typos_in_a_row_still_leave_the_student_at_level_one(client, world):
    ws, student, slug, _assignment = world
    client.sign_in(student)
    _post(client, ws, slug, "P3-01", TYPO)
    _post(client, ws, slug, "P3-01", TYPO)

    text = _text(client.get(_url(ws, slug, "P3-01")))

    assert "Your entry, line by line" not in text


# ── the ordinary guarantees these routes inherit ───────────────────────────────────────

def test_an_unknown_problem_is_404(client, world):
    ws, student, slug, _assignment = world
    client.sign_in(student)

    assert client.get(_url(ws, slug, "P9-99")).status_code == 404
    assert client.post(_url(ws, slug, "P9-99")).status_code == 404
    assert client.post(_url(ws, slug, "P9-99") + "/answer").status_code == 404


def test_another_student_cannot_see_these_problems(client, session, world):
    """workspace_view answers 404, never 403, so a probe cannot confirm the workspace exists."""
    ws, _student, slug, _assignment = world
    intruder = User(email="intruder@example.edu", given_name="Bo", family_name="Adeyemi")
    session.add(intruder)
    session.flush()
    client.sign_in(intruder)

    assert client.get(_list_url(ws, slug)).status_code == 404
    assert client.get(_url(ws, slug, "P3-01")).status_code == 404


def test_a_submitted_workspace_is_read_only(client, session, world):
    """workspace_view already enforces it; this proves the new routes inherit it rather than
    writing their own path around it."""
    ws, student, slug, _assignment = world
    client.sign_in(student)
    ws.status = "submitted"
    session.flush()

    text = _text(client.get(_url(ws, slug, "P3-01")))

    assert "Record this entry" not in text
    assert "Show me this entry" not in text


def test_a_submitted_workspace_cannot_record_or_reveal(client, session, world):
    """The form being gone is not enough: a POST must not get through either."""
    ws, student, slug, _assignment = world
    client.sign_in(student)
    ws.status = "submitted"
    session.flush()

    _post(client, ws, slug, "P3-01", RIGHT)
    client.post(_url(ws, slug, "P3-01") + "/answer")
    session.expire_all()

    from originalentry.services.problems import attempt_for, live_entry
    assert attempt_for(session, ws, "P3-01") is None
    assert live_entry(session, ws, "P3-01") is None


# ── the account picker ─────────────────────────────────────────────────────────────────

def test_the_picker_offers_only_the_chapter_s_own_accounts(client, world):
    """`problems.chapter` synthesises a retained-earnings and an income-summary account to satisfy
    validator V5. No chapter problem touches either, and offering them would be two lines of
    noise in every problem a student works."""
    ws, student, slug, _assignment = world
    client.sign_in(student)

    text = _text(client.get(_url(ws, slug, "P3-01")))

    assert "101" in text and "150" in text
    assert "Retained Earnings" not in text
    assert "Income Summary" not in text
