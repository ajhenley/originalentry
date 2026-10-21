"""Which database the suite talks to, and whether it admits when that is production.

No database and no app: this is the selection, which has to be right before anything else can be
trusted. A warning that failed to fire would leave the suite silently writing to real student work,
which is the state this module exists to end.
"""

from __future__ import annotations

from tests.database_target import banner, resolve

PROD = "postgresql+psycopg://u:secret@ep-prod-pooler.c-4.us-west-2.aws.neon.tech/neondb"
PROD_DIRECT = "postgresql+psycopg://u:secret@ep-prod.c-4.us-west-2.aws.neon.tech/neondb"
BRANCH = "postgresql+psycopg://u:other@ep-dev-pooler.c-4.us-west-2.aws.neon.tech/neondb"
BRANCH_DIRECT = "postgresql+psycopg://u:other@ep-dev.c-4.us-west-2.aws.neon.tech/neondb"


def test_a_branch_is_used_when_it_is_a_different_host():
    target = resolve({"DATABASE_URL": PROD, "DATABASE_URL_DIRECT": PROD_DIRECT,
                      "TEST_DATABASE_URL": BRANCH, "TEST_DATABASE_URL_DIRECT": BRANCH_DIRECT})

    assert target.url == BRANCH
    assert target.url_direct == BRANCH_DIRECT
    assert target.warning is None
    assert target.is_production is False
    assert banner(target) == ""


def test_an_unset_branch_falls_back_to_production_and_says_so():
    target = resolve({"DATABASE_URL": PROD, "DATABASE_URL_DIRECT": PROD_DIRECT})

    assert target.url == PROD
    assert target.is_production is True
    assert "PRODUCTION" in target.warning
    assert "TEST_DATABASE_URL" in target.warning


def test_a_branch_url_on_the_production_host_is_refused_as_a_branch():
    """The dangerous case: somebody believes they are isolated and is not. A different database
    name on the same endpoint is still the same Neon compute."""
    same_host_different_db = PROD.replace("/neondb", "/neondb_test")

    target = resolve({"DATABASE_URL": PROD, "TEST_DATABASE_URL": same_host_different_db})

    assert target.url == PROD, "a same-host URL was trusted as a branch"
    assert target.is_production is True
    assert "same host" in target.warning


def test_a_blank_or_whitespace_branch_counts_as_unset():
    for value in ("", "   "):
        target = resolve({"DATABASE_URL": PROD, "TEST_DATABASE_URL": value})

        assert target.is_production is True, f"{value!r} was treated as a branch"


def test_the_direct_url_falls_back_to_the_pooled_one():
    """A branch set without its direct endpoint still works; migrations go through the pooler."""
    target = resolve({"DATABASE_URL": PROD, "TEST_DATABASE_URL": BRANCH})

    assert target.url_direct == BRANCH


def test_no_warning_ever_carries_a_password():
    """The banner goes to a terminal and into CI logs. It names a host, never a credential."""
    target = resolve({"DATABASE_URL": PROD, "DATABASE_URL_DIRECT": PROD_DIRECT})

    assert "secret" not in target.warning
    assert "secret" not in banner(target)
    assert "ep-prod-pooler.c-4.us-west-2.aws.neon.tech" in target.warning


def test_the_banner_is_hard_to_miss():
    target = resolve({"DATABASE_URL": PROD})

    assert banner(target).count("!" * 78) == 2
