
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from seeds.generators.transactions import generar_transacciones


class FakeSession:
    """Simula una sesión sin conectarse ni escribir en PostgreSQL."""

    def __init__(self):
        self.statements = []
        self.committed = False
        self.rolled_back = False

    def execute(self, statement):
        self.statements.append(statement)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


@pytest.fixture
def references():
    user_id = uuid4()
    device_id = uuid4()
    merchant_id = uuid4()

    usuarios = [{"id": user_id}]
    dispositivos = [{"id": device_id, "user_id": user_id}]
    comercios = [{"id": merchant_id}]

    return usuarios, dispositivos, comercios


def generate(cantidad, porcentaje, references, seed=42):
    session = FakeSession()
    usuarios, dispositivos, comercios = references

    transactions = generar_transacciones(
        session=session,
        usuarios=usuarios,
        dispositivos=dispositivos,
        comercios=comercios,
        cantidad=cantidad,
        fraud_percentage=porcentaje,
        seed=seed,
    )

    return transactions, session


def test_porcentaje_cero_genera_solo_normales(references):
    transactions, session = generate(100, 0, references)

    assert len(transactions) == 100
    assert sum(t["is_fraud"] for t in transactions) == 0
    assert all(t["fraud_pattern"] is None for t in transactions)
    assert session.committed
    assert len(session.statements) == 100


def test_porcentaje_diez_distribuye_fraude_y_patrones(references):
    transactions, session = generate(100, 10, references)

    fraudulent = [t for t in transactions if t["is_fraud"]]
    normal = [t for t in transactions if not t["is_fraud"]]

    assert len(transactions) == 100
    assert len(fraudulent) == 10
    assert len(normal) == 90

    assert {
        t["fraud_pattern"] for t in fraudulent
    } == {
        "MULE_ACTIVITY",
        "TRANSACTION_SPLITTING",
        "VELOCITY",
    }

    assert all(t["fraud_pattern"] is None for t in normal)
    assert session.committed


def test_porcentaje_cien_genera_todo_fraudulento(references):
    transactions, _ = generate(100, 100, references)

    assert len(transactions) == 100
    assert all(t["is_fraud"] for t in transactions)
    assert all(t["fraud_pattern"] for t in transactions)


def test_transacciones_tienen_campos_y_referencias_validas(references):
    transactions, _ = generate(100, 10, references)
    usuarios, dispositivos, comercios = references

    user_ids = {u["id"] for u in usuarios}
    device_ids = {d["id"] for d in dispositivos}
    merchant_ids = {m["id"] for m in comercios}

    for t in transactions:
        assert t["user_id"] in user_ids
        assert t["device_id"] in device_ids
        assert t["merchant_id"] in merchant_ids
        assert isinstance(t["amount"], Decimal)
        assert t["amount"] > 0
        assert isinstance(t["transaction_date"], datetime)
        assert t["channel"] in {"WEB", "MOBILE", "ATM", "POS"}


def test_ids_son_deterministas(references):
    first, _ = generate(100, 10, references, seed=42)
    second, _ = generate(100, 10, references, seed=42)

    assert [t["id"] for t in first] == [t["id"] for t in second]


@pytest.mark.parametrize("percentage", [-1, 101])
def test_rechaza_porcentajes_invalidos(references, percentage):
    session = FakeSession()
    usuarios, dispositivos, comercios = references

    with pytest.raises(ValueError, match="porcentaje"):
        generar_transacciones(
            session,
            usuarios,
            dispositivos,
            comercios,
            cantidad=100,
            fraud_percentage=percentage,
        )

    assert session.statements == []
    assert not session.committed


def test_rechaza_cantidad_negativa(references):
    session = FakeSession()
    usuarios, dispositivos, comercios = references

    with pytest.raises(ValueError, match="cantidad"):
        generar_transacciones(
            session,
            usuarios,
            dispositivos,
            comercios,
            cantidad=-1,
            fraud_percentage=0,
        )

    assert session.statements == []


def test_cantidad_cero_no_inserta(references):
    transactions, session = generate(0, 0, references)

    assert transactions == []
    assert session.statements == []
    assert not session.committed
