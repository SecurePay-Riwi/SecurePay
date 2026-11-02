import pytest

from services.decision_engine import publisher


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
