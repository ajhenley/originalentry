"""Integration-test harness. Real Postgres (Neon), because triggers, composite keys and locks
are part of the design (T17.1). Every test runs inside one transaction that is rolled back, so
nothing persists to the database.
"""

import pytest
from parchment.app import create_app
from parchment.extensions import db
from sqlalchemy.orm import Session

pytestmark = pytest.mark.db


@pytest.fixture(scope="session")
def app():
    return create_app()


@pytest.fixture
def session(app):
    with app.app_context():
        connection = db.engine.connect()
        trans = connection.begin()
        s = Session(bind=connection, expire_on_commit=False)
        try:
            yield s
        finally:
            s.close()
            if trans.is_active:  # a test may have rolled back after a forced constraint check
                trans.rollback()
            connection.close()
