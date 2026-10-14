"""Publicador de decisiones, con un SNS de mentira (no necesita LocalStack)."""

import logging
import threading
import time

from services.decision_engine.publisher import MARCA_FALLA, Publicador

TEMA = "arn:aws:sns:us-east-2:000000000000:decisiones"


class SnsFalso:
    """Registra cada publish_batch. `fallar` decide qué Ids rechazar."""

    def __init__(self, fallar=None, bloqueo=None):
        self.lotes = []
        self.fallar = fallar or (lambda llamada, ids: set())
        self.bloqueo = bloqueo

    def publish_batch(self, TopicArn, PublishBatchRequestEntries):
        if self.bloqueo is not None:
            self.bloqueo.wait(5)
        ids = [e["Id"] for e in PublishBatchRequestEntries]
        self.lotes.append(PublishBatchRequestEntries)
        rechazados = self.fallar(len(self.lotes), ids)
        return {
            "Successful": [{"Id": i} for i in ids if i not in rechazados],
            "Failed": [
                {"Id": i, "Code": "InternalError", "Message": "falla", "SenderFault": False}
                for i in rechazados
            ],
        }


def _publicador(sns, **kwargs):
    opciones = {"espera_lote_s": 0.2, "reintentos": 2, "espera_reintento_s": 0}
    opciones.update(kwargs)
    return Publicador(topic_arn=TEMA, crear_cliente=lambda: sns, **opciones)


def test_groups_events_in_batches_of_ten():
    sns = SnsFalso()
    pub = _publicador(sns)

    for i in range(25):
        pub.publicar({"n": i})
    pub.detener()

    assert [len(lote) for lote in sns.lotes] == [10, 10, 5]
    assert pub.estado() == {"pendientes": 0, "publicados": 25, "fallidos": 0}


def test_publish_does_not_wait_for_sns():
    bloqueo = threading.Event()  # SNS "colgado" hasta que se libere
    sns = SnsFalso(bloqueo=bloqueo)
    pub = _publicador(sns, espera_lote_s=0)

    inicio = time.perf_counter()
    for i in range(5):
        pub.publicar({"n": i})
    duracion = time.perf_counter() - inicio

    assert duracion < 0.05
    bloqueo.set()
    pub.detener()
    assert pub.publicados == 5


def test_retries_only_the_failed_entries():
    # Primera llamada: SNS rechaza el Id "1". Segunda: acepta.
    sns = SnsFalso(fallar=lambda llamada, ids: {"1"} if llamada == 1 else set())
    pub = _publicador(sns)

    for i in range(3):
        pub.publicar({"n": i})
    pub.detener()

    assert [len(lote) for lote in sns.lotes] == [3, 1]
    assert pub.publicados == 3
    assert pub.fallidos == 0


def test_logs_the_event_when_sns_keeps_failing(caplog):
    def sns_caido():
        raise ConnectionError("SNS no responde")

    pub = Publicador(
        topic_arn=TEMA, crear_cliente=sns_caido, reintentos=2, espera_reintento_s=0
    )

    with caplog.at_level(logging.ERROR):
        pub.publicar({"transaction": {"id": "abc"}})
        pub.detener()

    assert pub.fallidos == 1
    assert MARCA_FALLA in caplog.text
    assert '"id": "abc"' in caplog.text  # el evento completo, para republicarlo


def test_full_buffer_registers_failure_without_blocking(caplog):
    bloqueo = threading.Event()
    sns = SnsFalso(bloqueo=bloqueo)
    pub = _publicador(sns, capacidad=1, espera_lote_s=0)

    pub.publicar({"n": 0})  # el hilo lo toma y se queda esperando a SNS
    time.sleep(0.05)
    pub.publicar({"n": 1})  # ocupa el único lugar
    inicio = time.perf_counter()
    pub.publicar({"n": 2})  # ya no cabe
    assert time.perf_counter() - inicio < 0.05

    assert pub.fallidos == 1
    assert "cola en memoria está llena" in caplog.text

    bloqueo.set()
    pub.detener()
    assert pub.publicados == 2


def test_missing_topic_is_a_registered_failure(caplog):
    pub = Publicador(topic_arn="", crear_cliente=SnsFalso)

    pub.publicar({"n": 0})
    pub.detener()

    assert pub.fallidos == 1
    assert "SNS_DECISIONES_TOPIC_ARN" in caplog.text
