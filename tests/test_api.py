
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from threading import Barrier
from time import perf_counter
from uuid import uuid4

from fastapi.testclient import TestClient

from api.main import app
from seeds.db import get_session
from seeds.models import Usuario, Dispositivo, Comercio, Transaccion
import pytest

from seeds.models import (
    Usuario,
    Dispositivo,
    Comercio,
    Transaccion,
    ListaRestrictiva,
)

from api.services.decision_service import HIGH_AMOUNT_THRESHOLD


client = TestClient(app)


def test_health_returns_200():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_invalid_transaction_returns_400():
    response = client.post(
        "/transactions",
        json={},
    )

    assert response.status_code == 400
    assert "detail" in response.json()


def test_repeated_transaction_returns_same_decision():
    session = get_session()

    try:
        user = session.query(Usuario).first()
        merchant = session.query(Comercio).first()

        device = (
            session.query(Dispositivo)
            .filter(Dispositivo.user_id == user.id)
            .first()
            if user
            else None
        )

        assert user is not None, "Se necesita al menos un usuario"
        assert device is not None, "Se necesita un dispositivo válido"
        assert merchant is not None, "Se necesita al menos un comercio"

        payload = {
            "id": str(uuid4()),
            "user_id": str(user.id),
            "device_id": str(device.id),
            "merchant_id": str(merchant.id),
            "amount": "25000.00",
            "transaction_date": datetime.now(timezone.utc).isoformat(),
            "channel": "WEB",
        }
    finally:
        session.close()

    transaction_id = payload["id"]

    try:
        # Primera solicitud: procesa la transacción.
        first = client.post("/transactions", json=payload)

        assert first.status_code == 200, first.text
        assert first.json()["idempotent_replay"] is False

        # Segunda solicitud: reutiliza la decisión guardada.
        second = client.post("/transactions", json=payload)

        assert second.status_code == 200, second.text
        assert second.json()["idempotent_replay"] is True
        assert second.json()["decision"] == first.json()["decision"]

        # Verificar que exista un único registro.
        verification_session = get_session()
        try:
            count = (
                verification_session.query(Transaccion)
                .filter(Transaccion.id == transaction_id)
                .count()
            )
            assert count == 1
        finally:
            verification_session.close()

    finally:
        # Limpiar únicamente el registro creado por esta prueba.
        cleanup_session = get_session()
        try:
            cleanup_session.query(Transaccion).filter(
                Transaccion.id == transaction_id
            ).delete(synchronize_session=False)
            cleanup_session.commit()
        except Exception:
            cleanup_session.rollback()
            raise
        finally:
            cleanup_session.close()


def test_transaction_response_time():
    session = get_session()

    try:
        user = session.query(Usuario).first()
        merchant = session.query(Comercio).first()

        device = (
            session.query(Dispositivo)
            .filter(Dispositivo.user_id == user.id)
            .first()
            if user
            else None
        )

        assert user is not None
        assert device is not None
        assert merchant is not None

        payload = {
            "id": str(uuid4()),
            "user_id": str(user.id),
            "device_id": str(device.id),
            "merchant_id": str(merchant.id),
            "amount": "25000.00",
            "transaction_date": datetime.now(timezone.utc).isoformat(),
            "channel": "WEB",
        }
    finally:
        session.close()

    transaction_id = payload["id"]

    try:
        # Medir la primera solicitud.
        start = perf_counter()
        first = client.post("/transactions", json=payload)
        first_ms = (perf_counter() - start) * 1000

        assert first.status_code == 200, first.text
        assert first_ms < 200, (
            f"La primera solicitud tardó {first_ms:.2f} ms"
        )

        # Medir la solicitud repetida.
        start = perf_counter()
        second = client.post("/transactions", json=payload)
        replay_ms = (perf_counter() - start) * 1000

        assert second.status_code == 200, second.text
        assert second.json()["idempotent_replay"] is True
        assert replay_ms < 200, (
            f"La solicitud repetida tardó {replay_ms:.2f} ms"
        )

        print(f"\nPrimera solicitud: {first_ms:.2f} ms")
        print(f"Solicitud repetida: {replay_ms:.2f} ms")

    finally:
        cleanup = get_session()
        try:
            cleanup.query(Transaccion).filter(
                Transaccion.id == transaction_id
            ).delete(synchronize_session=False)
            cleanup.commit()
        except Exception:
            cleanup.rollback()
            raise
        finally:
            cleanup.close()


def test_expired_idempotency_window_returns_conflict():
    session = get_session()

    try:
        user = session.query(Usuario).first()
        merchant = session.query(Comercio).first()

        device = (
            session.query(Dispositivo)
            .filter(Dispositivo.user_id == user.id)
            .first()
            if user
            else None
        )

        assert user is not None
        assert device is not None
        assert merchant is not None

        payload = {
            "id": str(uuid4()),
            "user_id": str(user.id),
            "device_id": str(device.id),
            "merchant_id": str(merchant.id),
            "amount": "25000.00",
            "transaction_date": datetime.now(timezone.utc).isoformat(),
            "channel": "WEB",
        }
    finally:
        session.close()

    transaction_id = payload["id"]

    try:
        # Crear la transacción normalmente.
        first = client.post("/transactions", json=payload)
        assert first.status_code == 200, first.text

        # Simular que la decisión se guardó hace 25 horas.
        expired_session = get_session()
        try:
            transaction = expired_session.get(
                Transaccion,
                transaction_id,
            )
            assert transaction is not None

            transaction.processed_at = (
                datetime.now(timezone.utc) - timedelta(hours=25)
            )
            expired_session.commit()
        finally:
            expired_session.close()

        # La ventana configurada es de 24 horas.
        repeated = client.post("/transactions", json=payload)

        assert repeated.status_code == 409, repeated.text
        assert "ventana de idempotencia expiró" in (
            repeated.json()["detail"]
        )

        # Verificar que el registro original siga siendo único.
        verification = get_session()
        try:
            count = (
                verification.query(Transaccion)
                .filter(Transaccion.id == transaction_id)
                .count()
            )
            assert count == 1
        finally:
            verification.close()

    finally:
        # Eliminar únicamente la transacción creada por esta prueba.
        cleanup = get_session()
        try:
            cleanup.query(Transaccion).filter(
                Transaccion.id == transaction_id
            ).delete(synchronize_session=False)
            cleanup.commit()
        except Exception:
            cleanup.rollback()
            raise
        finally:
            cleanup.close()


def test_simultaneous_requests_do_not_create_duplicates():
    session = get_session()

    try:
        user = session.query(Usuario).first()
        merchant = session.query(Comercio).first()

        device = (
            session.query(Dispositivo)
            .filter(Dispositivo.user_id == user.id)
            .first()
            if user
            else None
        )

        assert user is not None
        assert device is not None
        assert merchant is not None

        payload = {
            "id": str(uuid4()),
            "user_id": str(user.id),
            "device_id": str(device.id),
            "merchant_id": str(merchant.id),
            "amount": "25000.00",
            "transaction_date": datetime.now(timezone.utc).isoformat(),
            "channel": "WEB",
        }
    finally:
        session.close()

    transaction_id = payload["id"]
    barrier = Barrier(2)

    def send_request():
        barrier.wait(timeout=10)
        return client.post("/transactions", json=payload)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(send_request),
                executor.submit(send_request),
            ]
            responses = [
                future.result(timeout=20)
                for future in futures
            ]

        assert all(
            response.status_code == 200 for response in responses
        ), [response.status_code for response in responses]

        bodies = [response.json() for response in responses]

        assert bodies[0]["transaction_id"] == transaction_id
        assert bodies[1]["transaction_id"] == transaction_id
        assert bodies[0]["decision"] == bodies[1]["decision"]

        # Una solicitud nueva y otra repetida, sin duplicados.
        assert sorted(
            body["idempotent_replay"] for body in bodies
        ) == [False, True]

        verification = get_session()
        try:
            count = (
                verification.query(Transaccion)
                .filter(Transaccion.id == transaction_id)
                .count()
            )
            assert count == 1
        finally:
            verification.close()

    finally:
        cleanup = get_session()
        try:
            cleanup.query(Transaccion).filter(
                Transaccion.id == transaction_id
            ).delete(synchronize_session=False)
            cleanup.commit()
        except Exception:
            cleanup.rollback()
            raise
        finally:
            cleanup.close()


@pytest.mark.parametrize(
    "scenario,amount,expected_decision",
    [
        ("approve", "25000.00", "APPROVE"),
        (
            "hold",
            str(max(1, HIGH_AMOUNT_THRESHOLD)),
            "HOLD",
        ),
        ("reject", "25000.00", "REJECT"),
    ],
)
def test_business_decisions_are_persisted(
    scenario,
    amount,
    expected_decision,
):
    session = get_session()
    transaction_id = uuid4()
    restricted_document = None

    try:
        # Buscar un usuario que inicialmente no esté restringido.
        user = (
            session.query(Usuario)
            .outerjoin(
                ListaRestrictiva,
                Usuario.documento == ListaRestrictiva.documento,
            )
            .filter(ListaRestrictiva.id.is_(None))
            .first()
        )

        assert user is not None, (
            "Se necesita un usuario que no esté en la lista restrictiva."
        )

        device = (
            session.query(Dispositivo)
            .filter(Dispositivo.user_id == user.id)
            .first()
        )
        merchant = session.query(Comercio).first()

        assert device is not None
        assert merchant is not None

        # Solo el escenario REJECT agrega temporalmente al usuario
        # a la lista restrictiva.
        if scenario == "reject":
            restricted_document = user.documento
            session.add(
                ListaRestrictiva(
                    documento=restricted_document,
                    tipo="TEST",
                    fecha_inclusion=datetime.now().date(),
                )
            )
            session.commit()

        payload = {
            "id": str(transaction_id),
            "user_id": str(user.id),
            "device_id": str(device.id),
            "merchant_id": str(merchant.id),
            "amount": amount,
            "transaction_date": datetime.now(timezone.utc).isoformat(),
            "channel": "WEB",
        }

    finally:
        session.close()

    try:
        response = client.post("/transactions", json=payload)

        assert response.status_code == 200, response.text

        body = response.json()
        assert body["decision"] == expected_decision
        assert body["idempotent_replay"] is False
        assert body["decision_reason"]
        assert body["processed_at"]

        # Comprobar la persistencia en PostgreSQL.
        verification = get_session()
        try:
            saved = verification.get(Transaccion, transaction_id)

            assert saved is not None
            assert saved.decision == expected_decision
            assert saved.decision_reason == body["decision_reason"]
            assert saved.processed_at is not None
        finally:
            verification.close()

    finally:
        # Limpiar solo los datos creados por esta prueba.
        cleanup = get_session()
        try:
            cleanup.query(Transaccion).filter(
                Transaccion.id == transaction_id
            ).delete(synchronize_session=False)

            if restricted_document is not None:
                cleanup.query(ListaRestrictiva).filter(
                    ListaRestrictiva.documento == restricted_document,
                    ListaRestrictiva.tipo == "TEST",
                ).delete(synchronize_session=False)

            cleanup.commit()
        except Exception:
            cleanup.rollback()
            raise
        finally:
            cleanup.close()

def test_database_error_returns_500():
    from sqlalchemy.exc import SQLAlchemyError
    from api.main import get_db

    class FailingSession:
        rolled_back = False

        def get(self, *args, **kwargs):
            raise SQLAlchemyError("Fallo simulado de base de datos")

        def rollback(self):
            self.rolled_back = True

    fake_session = FailingSession()

    def override_get_db():
        yield fake_session

    app.dependency_overrides[get_db] = override_get_db

    payload = {
        "id": str(uuid4()),
        "user_id": str(uuid4()),
        "device_id": str(uuid4()),
        "merchant_id": str(uuid4()),
        "amount": "25000.00",
        "transaction_date": datetime.now(timezone.utc).isoformat(),
        "channel": "WEB",
    }

    try:
        response = client.post("/transactions", json=payload)
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 500
    assert response.json()["detail"] == (
        "Error interno al procesar la transacción."
    )
    assert fake_session.rolled_back is True
