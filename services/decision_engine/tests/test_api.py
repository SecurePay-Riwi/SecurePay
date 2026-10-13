
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from threading import Barrier
from time import perf_counter
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func

from services.decision_engine import publisher
from services.decision_engine.main import app
from services.decision_engine.publisher import MARCA_FALLA, Publicador
from shared.cache import get_cache
from shared.db import get_session
from shared.models import (
    Comercio,
    Cuenta,
    DispositivoCuenta,
    ListaRestrictiva,
    Usuario,
)


client = TestClient(app)

# El documento del usuario con solo dígitos, como lo guarda la lista.
DOCUMENTO_NORMALIZADO = func.regexp_replace(Usuario.documento, r"\D", "", "g")


def _cuenta_del_seed(en_lista: bool) -> Cuenta:
    """Una cuenta activa del seed cuyo titular está o no en la lista."""
    session = get_session()

    try:
        consulta = (
            session.query(Cuenta)
            .join(Usuario, Usuario.id == Cuenta.user_id)
            .outerjoin(
                ListaRestrictiva,
                ListaRestrictiva.documento == DOCUMENTO_NORMALIZADO,
            )
            .join(DispositivoCuenta, DispositivoCuenta.cuenta_id == Cuenta.id)
            .filter(Cuenta.estado == "activa", Cuenta.saldo >= 100)
        )

        if en_lista:
            consulta = consulta.filter(ListaRestrictiva.id.isnot(None))
        else:
            consulta = consulta.filter(ListaRestrictiva.id.is_(None))

        cuenta = consulta.order_by(Cuenta.id).first()

        assert cuenta is not None, (
            "Se necesita el seed cargado: no hay una cuenta activa "
            f"con titular {'en' if en_lista else 'fuera de'} la lista."
        )

        session.expunge(cuenta)
        return cuenta
    finally:
        session.close()


def _payload_qr(cuenta: Cuenta, amount: str | None = None) -> dict:
    """Un pago QR válido desde la cuenta, con un id nuevo cada vez."""
    session = get_session()

    try:
        dispositivo = (
            session.query(DispositivoCuenta)
            .filter(DispositivoCuenta.cuenta_id == cuenta.id)
            .first()
        )
        comercio = session.query(Comercio).first()

        assert dispositivo is not None, "La cuenta necesita un dispositivo"
        assert comercio is not None, "Se necesita al menos un comercio"

        # El yen no lleva decimales.
        if amount is None:
            amount = "10" if cuenta.moneda == "JPY" else "10.00"

        return {
            "id": str(uuid4()),
            "type": "QR",
            "channel": "APP",
            "source_account_id": str(cuenta.id),
            "destination_account_id": None,
            "merchant_id": str(comercio.id),
            "amount": amount,
            "currency": cuenta.moneda,
            "source_balance_before": str(cuenta.saldo),
            "source_balance_after": str(cuenta.saldo - Decimal(amount)),
            "destination_balance_before": None,
            "destination_balance_after": None,
            "device_id": str(dispositivo.dispositivo_id),
            "transaction_date": datetime.now(timezone.utc).isoformat(),
        }
    finally:
        session.close()


def _payload_normal(amount: str | None = None) -> dict:
    return _payload_qr(_cuenta_del_seed(en_lista=False), amount)


def test_health_returns_200():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert set(response.json()["messaging"]) == {"pendientes", "publicados", "fallidos"}


def test_invalid_transaction_returns_400():
    response = client.post(
        "/transactions",
        json={},
    )

    assert response.status_code == 400
    assert "detail" in response.json()


def test_repeated_transaction_returns_same_decision():
    payload = _payload_normal()

    # Primera solicitud: decide la transacción.
    first = client.post("/transactions", json=payload)

    assert first.status_code == 200, first.text
    assert first.json()["transaction_id"] == payload["id"]
    assert first.json()["decision"] == "APPROVE"
    assert first.json()["idempotent_replay"] is False

    # Segunda solicitud: reutiliza la decisión guardada en Valkey.
    second = client.post("/transactions", json=payload)

    assert second.status_code == 200, second.text
    assert second.json()["idempotent_replay"] is True
    assert second.json()["decision"] == first.json()["decision"]
    assert second.json()["processed_at"] == first.json()["processed_at"]


def test_simultaneous_requests_decide_only_once():
    payload = _payload_normal()
    peticiones = 10
    barrier = Barrier(peticiones)

    def send_request():
        barrier.wait(timeout=10)
        return client.post("/transactions", json=payload)

    with ThreadPoolExecutor(max_workers=peticiones) as executor:
        futures = [executor.submit(send_request) for _ in range(peticiones)]
        responses = [future.result(timeout=20) for future in futures]

    assert all(
        response.status_code == 200 for response in responses
    ), [response.status_code for response in responses]

    bodies = [response.json() for response in responses]

    assert {body["transaction_id"] for body in bodies} == {payload["id"]}
    assert len({body["decision"] for body in bodies}) == 1
    assert len({body["processed_at"] for body in bodies}) == 1

    # Solo una decidió; las demás recibieron esa misma decisión.
    replays = [body["idempotent_replay"] for body in bodies]
    assert replays.count(False) == 1
    assert replays.count(True) == peticiones - 1


def test_same_id_with_different_amount_returns_conflict():
    cuenta = _cuenta_del_seed(en_lista=False)
    payload = _payload_qr(cuenta)

    first = client.post("/transactions", json=payload)
    assert first.status_code == 200, first.text

    otro = _payload_qr(cuenta, amount="20")
    otro["id"] = payload["id"]

    second = client.post("/transactions", json=otro)

    assert second.status_code == 409, second.text
    assert second.json()["detail"] == "El id ya se usó con otro contenido."


def test_owner_on_restricted_list_is_rejected():
    payload = _payload_qr(_cuenta_del_seed(en_lista=True))

    response = client.post("/transactions", json=payload)

    assert response.status_code == 200, response.text
    assert response.json()["decision"] == "REJECT"
    assert response.json()["decision_reason"] == (
        "Titular incluido en una lista restrictiva."
    )


def test_nonexistent_account_returns_422():
    payload = _payload_normal()
    payload["source_account_id"] = str(uuid4())

    response = client.post("/transactions", json=payload)

    assert response.status_code == 422, response.text
    assert "no existe" in response.json()["detail"]


def test_amount_with_too_many_decimals_returns_400():
    payload = _payload_normal()
    payload["amount"] = "88.913"

    response = client.post("/transactions", json=payload)

    assert response.status_code == 400, response.text
    assert "detail" in response.json()


def test_amount_with_trailing_zeros_is_accepted():
    payload = _payload_normal(amount="10.000")

    response = client.post("/transactions", json=payload)

    assert response.status_code == 200, response.text


def test_transaction_response_time():
    payload = _payload_normal()

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


def test_database_error_returns_500_and_releases_reservation():
    from sqlalchemy.exc import SQLAlchemyError
    from services.decision_engine.main import get_db

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

    payload = _payload_normal()

    try:
        response = client.post("/transactions", json=payload)
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 500
    assert response.json()["detail"] == (
        "Error interno al procesar la transacción."
    )
    assert fake_session.rolled_back is True

    # La reserva se liberó: el reintento decide en vez de recibir 409.
    retry = client.post("/transactions", json=payload)

    assert retry.status_code == 200, retry.text
    assert retry.json()["idempotent_replay"] is False


def _payloads_p2p(fechas: list[datetime]) -> list[dict]:
    """Transferencias P2P desde una cuenta del seed, una por fecha.

    Se borra el historial de velocidad de la cuenta para no heredar el de
    otra prueba o el de una corrida del generador.
    """
    session = get_session()

    try:
        origen, dispositivo = (
            session.query(Cuenta, DispositivoCuenta)
            .join(DispositivoCuenta, DispositivoCuenta.cuenta_id == Cuenta.id)
            .join(Usuario, Usuario.id == Cuenta.user_id)
            .outerjoin(
                ListaRestrictiva,
                ListaRestrictiva.documento == DOCUMENTO_NORMALIZADO,
            )
            .filter(Cuenta.estado == "activa", ListaRestrictiva.id.is_(None))
            .order_by(Cuenta.id)
            .first()
        )
        get_cache().delete(f"vel:{origen.id}")
        destino = (
            session.query(Cuenta)
            .filter(Cuenta.moneda == origen.moneda, Cuenta.id != origen.id)
            .first()
        )

        assert destino is not None, "Se necesitan dos cuentas en la misma moneda"

        amount = "1" if origen.moneda == "JPY" else "1.00"
        payloads = []

        for i, fecha in enumerate(fechas):
            payloads.append({
                "id": str(uuid4()),
                "type": "P2P",
                "channel": "APP",
                "source_account_id": str(origen.id),
                "destination_account_id": str(destino.id),
                "merchant_id": None,
                "amount": amount,
                "currency": origen.moneda,
                "source_balance_before": str(origen.saldo - i),
                "source_balance_after": str(origen.saldo - i - 1),
                "destination_balance_before": str(destino.saldo + i),
                "destination_balance_after": str(destino.saldo + i + 1),
                "device_id": str(dispositivo.dispositivo_id),
                "transaction_date": fecha.isoformat(),
            })

        return payloads
    finally:
        session.close()


def _decisiones(payloads: list[dict]) -> list[str]:
    decisiones = []

    for payload in payloads:
        response = client.post("/transactions", json=payload)
        assert response.status_code == 200, response.text
        decisiones.append(response.json()["decision"])

    return decisiones


def _minutos(*minutos) -> list[datetime]:
    base = datetime.now(timezone.utc)
    return [base + timedelta(minutes=m) for m in minutos]


def test_sixth_transfer_in_ten_minutes_is_held():
    payloads = _payloads_p2p(_minutos(0, 1.6, 3.2, 4.8, 6.4, 8))

    assert _decisiones(payloads) == ["APPROVE"] * 5 + ["HOLD"]


def test_five_transfers_in_ten_minutes_are_approved():
    payloads = _payloads_p2p(_minutos(0, 2, 4, 6, 8))

    assert _decisiones(payloads) == ["APPROVE"] * 5


def test_late_transfer_that_completes_the_window_is_held():
    # La del minuto 2 llega al final, después de las otras cinco.
    payloads = _payloads_p2p(_minutos(0, 1, 3, 4, 5, 2))

    assert _decisiones(payloads) == ["APPROVE"] * 5 + ["HOLD"]


def test_decision_is_published_once(eventos_publicados):
    payload = _payload_normal()

    first = client.post("/transactions", json=payload)
    second = client.post("/transactions", json=payload)

    assert first.status_code == second.status_code == 200
    # El reenvío devuelve la misma decisión sin publicarla otra vez.
    assert len(eventos_publicados) == 1

    evento = eventos_publicados[0]
    assert evento["event_type"] == "transaction.decided"
    assert evento["transaction"]["id"] == payload["id"]
    assert evento["transaction"]["amount"] == payload["amount"]
    assert evento["decision"]["decision"] == first.json()["decision"]


def test_engine_answers_when_sns_is_down(monkeypatch, caplog):
    def sns_caido():
        raise ConnectionError("SNS no responde")

    caido = Publicador(
        topic_arn="arn:aws:sns:us-east-2:000000000000:decisiones",
        crear_cliente=sns_caido,
        reintentos=1,
        espera_reintento_s=0,
    )
    monkeypatch.setattr(publisher, "publicar", caido.publicar)

    inicio = perf_counter()
    response = client.post("/transactions", json=_payload_normal())
    duracion = perf_counter() - inicio

    assert response.status_code == 200, response.text
    assert response.json()["decision"] == "APPROVE"
    assert duracion < 0.2

    # La falla queda registrada en el log, con el evento.
    caido.detener()
    assert caido.fallidos == 1
    assert MARCA_FALLA in caplog.text
