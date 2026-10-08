"""The people and the two sections the scoping matrix walks.

The builders live in ``tests/scoping_world.py``, which says why every one of them commits; these
are the fixtures that name them. Nothing here reaches for a pre-existing row and skips when there
is none: a test that skips is a test that can stop running unnoticed.
"""

from __future__ import annotations

import pytest
from originalentry.models import ROLE_ADMIN

from tests.scoping_world import foreign_world, staff_account, worked_world


@pytest.fixture
def owner(session):
    """The teacher of the section in ``worked``."""
    return staff_account(session, "scoping-owner@example.edu", name="Ada")


@pytest.fixture
def outsider(session):
    """A teacher who teaches nothing at all, and so may see nothing at all."""
    return staff_account(session, "scoping-outsider@example.edu", name="Noa")


@pytest.fixture
def admin(session):
    """An administrator, who sees every section without teaching any of them."""
    return staff_account(session, "scoping-admin@example.edu", role=ROLE_ADMIN, name="Rae")


@pytest.fixture
def worked(session, owner):
    return worked_world(session, owner)


@pytest.fixture
def foreign(session):
    return foreign_world(session)
