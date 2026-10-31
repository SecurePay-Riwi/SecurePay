"""The cases API against an empty PostgreSQL schema of its own, so the
tables of the dev database are never touched.

Needs PostgreSQL (DATABASE_URL).
"""

import pytest
from fastapi.testclient import TestClient

from services.cases_api import deps
from services.cases_api.main import app
from shared.tests.isolated_db import isolated_sessions


@pytest.fixture
def sessions():
    """The session factory the API uses during the test."""
    with isolated_sessions("cases_api_test") as factory:
        previous = deps.SessionLocal
        deps.bind(factory)
        try:
            yield factory
        finally:
            deps.bind(previous)


@pytest.fixture
def client(sessions):
    # The context runs the lifespan: create_schema().
    with TestClient(app) as c:
        yield c
