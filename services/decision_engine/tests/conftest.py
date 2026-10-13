import pytest

from services.decision_engine import publisher


@pytest.fixture(autouse=True)
def eventos_publicados(monkeypatch):
    """En las pruebas del motor nada sale a SNS: los eventos quedan aquí."""
    eventos = []
    monkeypatch.setattr(publisher, "publicar", eventos.append)
    return eventos
