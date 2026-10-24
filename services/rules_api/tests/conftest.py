"""Each test gets an empty PostgreSQL schema of its own, so the tables of
the dev database are never touched, and the {rules} keys are removed
from Valkey afterwards, so the engine tests decide with the defaults.

Needs PostgreSQL (DATABASE_URL) and Valkey.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from services.rules_api import store
from services.rules_api.main import app
from shared.cache import get_cache
from shared.db import engine as dev_engine
from shared.rule_catalog import CATALOG_KEY, VERSION_KEY

SCHEMA = "rules_api_test"


@pytest.fixture
def isolated():
    with dev_engine.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))
        conn.execute(text(f"CREATE SCHEMA {SCHEMA}"))
    engine = create_engine(
        dev_engine.url, connect_args={"options": f"-csearch_path={SCHEMA}"}, pool_size=20,
    )
    previous = store.SessionLocal
    store.bind(sessionmaker(bind=engine))
    get_cache().delete(CATALOG_KEY, VERSION_KEY)
    try:
        yield engine
    finally:
        store.bind(previous)
        engine.dispose()
        get_cache().delete(CATALOG_KEY, VERSION_KEY)
        with dev_engine.begin() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))


@pytest.fixture
def client(isolated):
    # The context runs the lifespan: tables, version 1 and the publish.
    with TestClient(app) as c:
        yield c
