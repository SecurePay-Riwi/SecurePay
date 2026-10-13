
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
import valkey

from services.decision_engine import idempotency
from services.decision_engine.idempotency import (
    EnProceso,
    IdReutilizado,
    guardar,
    huella,
    liberar,
    reservar,
)
from shared.cache import get_cache


RESULTADO = {"decision": "APPROVE", "decision_reason": "Prueba"}


@pytest.fixture
def tx_id():
    """Id único por prueba; se omite la prueba si Valkey no está levantado."""
    try:
        get_cache().ping()
    except valkey.exceptions.ConnectionError:
        pytest.skip("Valkey no está disponible en VALKEY_URL")

    transaction_id = str(uuid4())
    yield transaction_id

    # Limpiar únicamente la clave creada por esta prueba.
    get_cache().delete(f"idem:{transaction_id}")


def test_fingerprint_ignores_key_order():
    assert huella({"a": 1, "b": 2}) == huella({"b": 2, "a": 1})
    assert huella({"a": 1}) != huella({"a": 2})


def test_first_request_wins_reservation(tx_id):
    assert reservar(tx_id, "firma") is None

    # La reserva debe vencer sola si el proceso muere antes de decidir.
    ttl = get_cache().ttl(f"idem:{tx_id}")
    assert 0 < ttl <= idempotency.RESERVA_TTL


def test_retry_while_pending_raises_in_progress(tx_id):
    assert reservar(tx_id, "firma") is None

    with pytest.raises(EnProceso):
        reservar(tx_id, "firma")


def test_retry_after_decision_returns_saved_result(tx_id):
    assert reservar(tx_id, "firma") is None
    guardar(tx_id, "firma", RESULTADO)

    assert reservar(tx_id, "firma") == RESULTADO

    ttl = get_cache().ttl(f"idem:{tx_id}")
    assert idempotency.RESERVA_TTL < ttl <= idempotency.TTL


def test_same_id_with_different_body_is_rejected(tx_id):
    assert reservar(tx_id, "firma") is None
    guardar(tx_id, "firma", RESULTADO)

    with pytest.raises(IdReutilizado):
        reservar(tx_id, "otra-firma")


def test_release_lets_the_retry_decide(tx_id):
    assert reservar(tx_id, "firma") is None
    liberar(tx_id)

    assert reservar(tx_id, "firma") is None


def test_simultaneous_requests_only_one_wins(tx_id):
    peticiones = 10
    barrier = Barrier(peticiones)

    def intentar():
        barrier.wait(timeout=10)
        try:
            return reservar(tx_id, "firma")
        except EnProceso:
            return "EN_PROCESO"

    with ThreadPoolExecutor(max_workers=peticiones) as executor:
        futures = [executor.submit(intentar) for _ in range(peticiones)]
        resultados = [future.result(timeout=20) for future in futures]

    assert resultados.count(None) == 1
    assert resultados.count("EN_PROCESO") == peticiones - 1
