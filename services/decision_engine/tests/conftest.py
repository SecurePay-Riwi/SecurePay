import logging

import pytest
from sqlalchemy.exc import OperationalError

from services.decision_engine import publisher

log = logging.getLogger(__name__)


@pytest.fixture(autouse=True)
def eventos_publicados(monkeypatch):
    """En las pruebas del motor nada sale a SNS: los eventos quedan aquí."""
    eventos = []
    monkeypatch.setattr(publisher, "publicar", eventos.append)
    return eventos


@pytest.fixture(autouse=True)
def fixed_rates():
    """No rate table loaded: the engine uses the fixed 2026-10-01 rates.
    A test that loads a table with currency.load() does not leave it
    for the next one."""
    from services.decision_engine import currency

    currency.load({})
    yield
    currency.load({})


@pytest.fixture(scope="session", autouse=True)
def reference_data_cache():
    """The engine reads accounts, merchants and the restricted list from
    the cache (HU-67): load them from the seeded PostgreSQL once, as the
    cache-loader service does in Compose. The tests import the loader
    only to prepare Valkey; the engine itself never does. Without
    PostgreSQL the unit tests still run."""
    from services.cache_loader import loader

    try:
        with loader.SessionLocal() as session:
            loader.load(session)
    except OperationalError:
        log.warning("PostgreSQL is not available: the cache was not loaded")
