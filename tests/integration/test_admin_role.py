"""The admin role, and the one definition of who counts as staff."""

from originalentry import decorators
from originalentry.auth import views as auth_views
from originalentry.models import ROLE_ADMIN, ROLE_GRADER, ROLE_INSTRUCTOR, ROLES


def test_admin_is_a_role_and_is_declared():
    assert ROLE_ADMIN == "admin"
    assert ROLE_ADMIN in ROLES


def test_admin_counts_as_staff():
    """Additive: every route a teacher reaches, an admin reaches."""
    assert decorators.STAFF_ROLES == frozenset({ROLE_GRADER, ROLE_INSTRUCTOR, ROLE_ADMIN})
    assert decorators.ADMIN_ROLES == frozenset({ROLE_ADMIN})


def test_who_counts_as_staff_is_defined_exactly_once():
    """auth/views.py kept its own copy of STAFF_ROLES. Two definitions of who counts as staff is
    a latent security bug, and duplication of this kind has already caused a defect here."""
    assert auth_views.STAFF_ROLES is decorators.STAFF_ROLES


def test_admin_fits_the_role_column():
    from originalentry.models.people import User
    assert len(ROLE_ADMIN) <= User.__table__.c.role.type.length
