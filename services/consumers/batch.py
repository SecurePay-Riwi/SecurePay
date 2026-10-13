"""Lo común a los tres consumidores: leer el lote y armar la respuesta.

Con ReportBatchItemFailures, la Lambda devuelve los ids de los mensajes
que fallaron. SQS borra los demás y solo esos vuelven a la cola; tras 5
intentos pasan a la cola de errores (bitácora sección 3).
"""

import logging

from shared.events import EventoInvalido, leer_evento

log = logging.getLogger(__name__)


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
