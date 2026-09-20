"""The public explanation of what this software is (How it works).

Written for someone who has never seen Original Entry: a department head weighing it up, an
instructor deciding whether to teach with it, a student's family wondering what the course bought.

It is part of the interface, so it is held to the interface's own rule (A7): the four judgemental
words stay out of it. Explaining "it never tells you your work is bad" without using those words
is a small discipline, and passing this test is the proof.
"""

import re

import pytest
from originalentry.app import create_app

BANNED = re.compile(r"\b(correct|incorrect|right|wrong)\b", re.IGNORECASE)
PUBLIC = ("/", "/how-it-works", "/privacy", "/terms")


@pytest.fixture(scope="module")
def client():
    return create_app().test_client()


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def test_it_is_readable_without_signing_in(client):
    response = client.get("/how-it-works")

    assert response.status_code == 200


def test_it_holds_to_the_rule_it_describes(client):
    text = _text(client.get("/how-it-works").get_data(as_text=True))

    assert not BANNED.search(text)


def test_it_says_what_the_software_actually_is(client):
    """A stranger's first question. Not a slogan — the work itself."""
    text = _text(client.get("/how-it-works").get_data(as_text=True)).lower()

    for word in ("accounting", "journal", "ledger", "trial balance", "statements"):
        assert word in text, word


def test_it_explains_the_marking_argument(client):
    """The reason this exists rather than a quiz tool: one slip is charged once."""
    text = _text(client.get("/how-it-works").get_data(as_text=True)).lower()

    assert "own figures" in text
    assert "answer key" in text


def test_it_shows_the_argument_rather_than_only_asserting_it(client):
    """Two marks for the same student's month, side by side."""
    body = client.get("/how-it-works").get_data(as_text=True)

    assert "34 / 100" in body
    assert "98 / 100" in body


def test_it_covers_what_an_instructor_gets(client):
    text = _text(client.get("/how-it-works").get_data(as_text=True)).lower()

    assert "variants" in text
    assert "csv" in text


def test_it_is_candid_about_what_it_does_not_do(client):
    text = _text(client.get("/how-it-works").get_data(as_text=True)).lower()

    assert "advertising" in text
    assert "javascript" in text


# ── The header ──────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", PUBLIC)
def test_every_public_page_offers_the_explanation(client, path):
    """A page nothing links to is a page nobody reads."""
    body = client.get(path, follow_redirects=True).get_data(as_text=True)

    assert "/how-it-works" in body
    assert "How it works" in body


def test_the_header_marks_the_page_you_are_on(client):
    body = client.get("/how-it-works").get_data(as_text=True)

    assert 'aria-current="page"' in body


def test_the_header_leads_back_to_the_front(client):
    body = client.get("/how-it-works").get_data(as_text=True)

    assert 'href="/"' in body


@pytest.mark.parametrize("path", PUBLIC)
def test_the_notice_and_the_policies_are_still_on_every_public_page(client, path):
    """The header is new; the footer's obligations did not change."""
    body = client.get(path, follow_redirects=True).get_data(as_text=True)

    assert "© 2026 AJ Henley" in body
    assert "/privacy" in body
    assert "/terms" in body
