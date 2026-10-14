"""Consumidor de historial (esqueleto).

Lee y confirma los eventos para que la cola no se acumule. Falta guardar
los pares dispositivo–cuenta en DynamoDB (solo cuando el par es nuevo) y
en la caché, que llega con las reglas de historial del sprint 2.
"""

import logging

from services.consumers.batch import leer_lote, respuesta

log = logging.getLogger(__name__)


def handler(event, context=None):
    validos, fallidos = leer_lote(event)
    log.debug("Historial: %d eventos leídos", len(validos))
    return respuesta(fallidos)
