"""The privacy policy, the terms, and the notice that sits on every page.

Both pages are readable without signing in: someone deciding whether to hand over their name and
their coursework should not have to hand it over first. They say what this app actually does —
what it keeps, who sees it, and what it never does — rather than the things a policy usually says.
"""

import re

import pytest
from parchment.app import create_app

BANNED = re.compile(r"\b(correct|incorrect|right|wrong)\b", re.IGNORECASE)
NOTICE = "© 2026 AJ Henley"


@pytest.fixture(scope="module")
def client():
    return create_app().test_client()


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def test_the_privacy_policy_is_readable_without_signing_in(client):
    response = client.get("/privacy")

    assert response.status_code == 200
    text = _text(response.get_data(as_text=True))
    assert "Privacy" in text
    assert not BANNED.search(text)


def test_it_says_what_is_kept_and_who_sees_it(client):
    text = _text(client.get("/privacy").get_data(as_text=True))

    assert "your instructor" in text.lower()
    assert "email" in text.lower()
    assert "sign-in" in text.lower()


def test_it_says_what_the_app_does_not_do(client):
    """The part a student actually wants: no advertising, no analytics, nothing sold."""
    text = _text(client.get("/privacy").get_data(as_text=True)).lower()

    assert "advertis" in text
    assert "analytics" in text or "tracking" in text
    assert "sold" in text


def test_the_terms_are_readable_without_signing_in(client):
    response = client.get("/terms")

    assert response.status_code == 200
    text = _text(response.get_data(as_text=True))
    assert "Terms" in text
    assert not BANNED.search(text)


def test_the_terms_cover_the_sign_in_link_and_other_students_books(client):
    text = _text(client.get("/terms").get_data(as_text=True)).lower()

    assert "sign-in link" in text
    assert "your own" in text


def test_every_page_carries_the_notice(client):
    for path in ("/", "/privacy", "/terms", "/auth/sign-in", "/join"):
        body = client.get(path, follow_redirects=True).get_data(as_text=True)
        assert NOTICE in body, f"{path} has no copyright notice"


def test_every_page_offers_both_documents(client):
    for path in ("/", "/privacy", "/terms", "/auth/sign-in"):
        body = client.get(path, follow_redirects=True).get_data(as_text=True)
        assert "/privacy" in body, f"{path} does not link to the privacy policy"
        assert "/terms" in body, f"{path} does not link to the terms"


def test_each_document_points_at_the_other(client):
    assert "/terms" in client.get("/privacy").get_data(as_text=True)
    assert "/privacy" in client.get("/terms").get_data(as_text=True)
