"""Lo común a los tres consumidores: leer el lote y armar la respuesta.

Con ReportBatchItemFailures, la Lambda devuelve los ids de los mensajes
que fallaron. SQS borra los demás y solo esos vuelven a la cola; tras 5
intentos pasan a la cola de errores (bitácora sección 3).
"""

import logging

from sqlalchemy.exc import SQLAlchemyError

from shared.cases import create_schema
from shared.events import EventoInvalido, leer_evento

log = logging.getLogger(__name__)

# Session factories whose case tables are already created (one per Lambda
# container; tests use a new factory each).
_schema_ready: set = set()


def leer_lote(event: dict) -> tuple[list[tuple[str, dict]], list[str]]:
    """Separa los mensajes en (id, evento) válidos e ids de los dañados.

    Un mensaje dañado se reporta como fallido: tras los reintentos llega a
    la cola de errores, donde alguien puede revisarlo.
    """
    validos, fallidos = [], []

    for registro in event.get("Records", []):
        mensaje_id = registro["messageId"]
        try:
            validos.append((mensaje_id, leer_evento(registro["body"])))
        except EventoInvalido as exc:
            log.error("Mensaje %s inválido: %s", mensaje_id, exc)
            fallidos.append(mensaje_id)

    return validos, fallidos


def respuesta(fallidos: list[str]) -> dict:
    return {"batchItemFailures": [{"itemIdentifier": i} for i in fallidos]}


def ensure_schema(session_factory) -> None:
    """Create the case tables (shared/cases.py) the first time a consumer
    writes in this process.

    Locally runner.py does it at startup; a Lambda has no startup step, so
    the cases and history consumers call this before their first write.
    create_schema() is idempotent and takes an advisory lock, so several
    Lambdas starting together are safe. If PostgreSQL is down it only logs:
    the write that follows fails too and the batch goes back to the queue.
    """
    if session_factory in _schema_ready:
        return
    try:
        with session_factory() as session:
            create_schema(session)
    except SQLAlchemyError:
        log.exception("Could not create the case tables; retrying on the next batch")
        return
    _schema_ready.add(session_factory)
