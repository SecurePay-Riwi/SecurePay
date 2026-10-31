"""Corre los consumidores en local contra las colas de LocalStack.

    uv run python -m services.consumers              # los tres
    uv run python -m services.consumers analitica    # solo uno

Hace lo que en AWS hace el servicio Lambda con un disparador de SQS: lee
lotes de hasta 10 mensajes, llama al handler y borra solo los que salieron
bien. Los fallidos vuelven a la cola cuando vence su tiempo de
invisibilidad (30 s) y, tras 5 intentos, pasan a la cola de errores.
"""

import logging
import sys
import threading

from sqlalchemy.exc import OperationalError

from shared import db
from shared.aws import cliente
from shared.cases import create_schema
from services.consumers import analytics, cases, history

log = logging.getLogger("services.consumers")

CONSUMIDORES = {
    "casos": cases.handler,
    "historial": history.handler,
    "analitica": analytics.handler,
}

# Espera larga de SQS (long polling): la llamada vuelve en cuanto hay
# mensajes o a los 10 s si no hay. Evita preguntar sin parar.
ESPERA_S = 10


def registro_sqs(mensaje: dict) -> dict:
    """Un mensaje de receive_message con la forma que le llega a Lambda."""
    return {
        "messageId": mensaje["MessageId"],
        "receiptHandle": mensaje["ReceiptHandle"],
        "body": mensaje["Body"],
        "attributes": mensaje.get("Attributes", {}),
        "eventSource": "aws:sqs",
    }


def atender_lote(sqs, cola_url: str, nombre: str, handler, espera_s=ESPERA_S) -> int:
    """Lee un lote, lo procesa y borra lo que salió bien. Devuelve cuántos leyó."""
    mensajes = sqs.receive_message(
        QueueUrl=cola_url,
        MaxNumberOfMessages=10,
        WaitTimeSeconds=espera_s,
        AttributeNames=["ApproximateReceiveCount"],
    ).get("Messages", [])

    if not mensajes:
        return 0

    try:
        resultado = handler({"Records": [registro_sqs(m) for m in mensajes]}, None)
        fallidos = {f["itemIdentifier"] for f in resultado.get("batchItemFailures", [])}
    except Exception:
        # Igual que en Lambda: si la función entera falla, el lote completo
        # vuelve a la cola.
        log.exception("%s: el handler falló con todo el lote", nombre)
        fallidos = {m["MessageId"] for m in mensajes}

    exitosos = [m for m in mensajes if m["MessageId"] not in fallidos]
    if exitosos:
        sqs.delete_message_batch(
            QueueUrl=cola_url,
            Entries=[
                {"Id": str(i), "ReceiptHandle": m["ReceiptHandle"]}
                for i, m in enumerate(exitosos)
            ],
        )

    log.info(
        "%s: %d procesados, %d devueltos a la cola",
        nombre,
        len(exitosos),
        len(fallidos),
    )
    return len(mensajes)


def atender(nombre: str, handler) -> None:
    sqs = cliente("sqs", read_timeout=ESPERA_S + 5)
    cola_url = None

    while True:
        try:
            if cola_url is None:
                cola_url = sqs.get_queue_url(QueueName=nombre)["QueueUrl"]
                log.info("%s: escuchando %s", nombre, cola_url)
            atender_lote(sqs, cola_url, nombre, handler)
        except Exception:
            log.exception("%s: no se pudo leer la cola; reintento", nombre)
            threading.Event().wait(2)


def prepare_database(session_factory=None, wait_s: float = 2) -> None:
    """Create the case tables (shared/cases.py) before reading any queue.
    PostgreSQL may still be starting with the rest of the stack: retry."""
    session_factory = session_factory or db.SessionLocal
    while True:
        try:
            with session_factory() as session:
                create_schema(session)
            return
        except OperationalError:
            log.warning("PostgreSQL is not available yet; retrying")
            threading.Event().wait(wait_s)


def main(argv: list[str]) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    nombres = argv or list(CONSUMIDORES)
    desconocidos = [n for n in nombres if n not in CONSUMIDORES]
    if desconocidos:
        sys.exit(f"Consumidor desconocido: {desconocidos}. Opciones: {list(CONSUMIDORES)}")

    prepare_database()

    hilos = [
        threading.Thread(target=atender, args=(n, CONSUMIDORES[n]), name=n, daemon=True)
        for n in nombres
    ]
    for hilo in hilos:
        hilo.start()

    try:
        for hilo in hilos:
            hilo.join()
    except KeyboardInterrupt:
        # Lo que estaba leído y sin borrar vuelve a la cola solo.
        log.info("Consumidores detenidos")
