"""Consumidor de casos (esqueleto).

Lee y confirma los eventos para que la cola no se acumule. Falta crear el
caso en PostgreSQL, que depende de una decisión de equipo abierta: qué
transacciones retenidas abren caso (bitácora, pregunta Q6) y de la tabla
de casos, que todavía no existe. Cuando se decida, va aquí, y debe
tolerar recibir dos veces el mismo evento (no crear dos casos para la
misma transacción).
"""

import logging

from services.consumers.batch import leer_lote, respuesta

log = logging.getLogger(__name__)


def handler(event, context=None):
    validos, fallidos = leer_lote(event)

    for _, evento in validos:
        decision = evento["decision"]
        if decision["decision"] != "APPROVE":
            log.info(
                "Casos: %s %s (%s). Crear el caso queda pendiente.",
                decision["decision"],
                decision["transaction_id"],
                decision["decision_reason"],
            )

    return respuesta(fallidos)
