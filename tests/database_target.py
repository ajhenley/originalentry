"""Which database the test suite talks to, and whether that is the production one.

The suite runs against real Postgres because triggers, composite keys and locks are part of the
design. Until now that was always the *production* Neon database, and nothing said so: a run that
accidentally escaped its transaction, or a fixture that committed outside a savepoint, was writing
to real student work.

``TEST_DATABASE_URL`` in ``.env`` points the suite at a Neon development branch instead. When it is
absent, or resolves to the same host as ``DATABASE_URL``, the suite still runs -- breaking every
test run would be worse -- but it says so loudly, every time, so the state is never silent.

Kept out of ``conftest.py`` and free of pytest so the selection can be tested on its own, which is
the only way to know the warning fires in the cases it is meant to.
"""

from __future__ import annotations

from dataclasses import dataclass

#: The keys a development branch is read from, and the production keys they stand in for.
TEST_URL = "TEST_DATABASE_URL"
TEST_URL_DIRECT = "TEST_DATABASE_URL_DIRECT"
PROD_URL = "DATABASE_URL"
PROD_URL_DIRECT = "DATABASE_URL_DIRECT"


@dataclass(frozen=True)
class Target:
    """Which URLs the suite should use, and what to say about it."""

    url: str
    url_direct: str
    #: None when the suite is on its own branch; otherwise why it is not.
    warning: str | None = None

    @property
    def is_production(self) -> bool:
        return self.warning is not None


def _host(url: str) -> str:
    """The host:port of a Postgres URL, with no credentials in it.

    Used for comparison and for the warning text, so neither can leak a password into a terminal
    or a CI log.
    """
    if "@" in url:
        url = url.rsplit("@", 1)[1]
    for separator in ("/", "?"):
        url = url.split(separator, 1)[0]
    return url


def resolve(env: dict[str, str]) -> Target:
    """Pick the database the suite runs against.

    A development branch is used only when it is set *and* its host differs from production's. A
    branch URL that resolves to the production host is the dangerous case -- somebody believes they
    are isolated and is not -- so it is reported rather than trusted.
    """
    production = env.get(PROD_URL, "")
    production_direct = env.get(PROD_URL_DIRECT, "") or production
    branch = (env.get(TEST_URL) or "").strip()
    branch_direct = (env.get(TEST_URL_DIRECT) or "").strip() or branch

    if not branch:
        return Target(
            url=production,
            url_direct=production_direct,
            warning=(
                f"{TEST_URL} is not set, so this run is against the PRODUCTION database "
                f"({_host(production)}), which holds real student work. Create a Neon development "
                f"branch and put its pooled and direct URLs in .env as {TEST_URL} and "
                f"{TEST_URL_DIRECT}."
            ),
        )

    if _host(branch) == _host(production):
        return Target(
            url=production,
            url_direct=production_direct,
            warning=(
                f"{TEST_URL} is set but resolves to the same host as {PROD_URL} "
                f"({_host(production)}), so it is NOT a separate branch. This run is against the "
                f"production database."
            ),
        )

    return Target(url=branch, url_direct=branch_direct)


def banner(target: Target) -> str:
    """The warning as a block that cannot be missed in a terminal, or '' when on a branch."""
    if target.warning is None:
        return ""
    rule = "!" * 78
    return f"\n{rule}\n  {target.warning}\n{rule}\n"
