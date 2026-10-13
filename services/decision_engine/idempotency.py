"""Idempotencia de transacciones en Valkey.

Cada transacción reserva su id con SET NX antes de decidir. Si el core
reenvía el mismo id, recibe la misma decisión mientras dure el TTL.
"""

import hashlib
import json
import os

from shared.cache import get_cache

TTL = int(os.getenv("IDEMPOTENCY_TTL_SECONDS", "3600"))
# Si el proceso muere a mitad de decidir, la reserva se libera sola.
RESERVA_TTL = 30


class EnProceso(Exception):
    """La primera petición con este id todavía está decidiendo."""


class IdReutilizado(Exception):
    """Mismo id con otro contenido: no es un reenvío, es un error del core."""


def _clave(tx_id):
    return f"idem:{tx_id}"


def huella(cuerpo: dict) -> str:
    texto = json.dumps(cuerpo, sort_keys=True, default=str)
    return hashlib.sha256(texto.encode()).hexdigest()


def reservar(tx_id, firma):
    """None: esta petición ganó y debe decidir. dict: decisión ya tomada."""
    r = get_cache()
    pendiente = json.dumps({"estado": "PENDING", "huella": firma})

    # NX: solo escribe si la clave no existe. Es atómico en Valkey,
    # así que de dos peticiones simultáneas solo una recibe True.
    if r.set(_clave(tx_id), pendiente, nx=True, ex=RESERVA_TTL):
        return None

    guardado = r.get(_clave(tx_id))
    if guardado is None:  # venció justo entre el SET y el GET
        return reservar(tx_id, firma)

    datos = json.loads(guardado)
    if datos["huella"] != firma:
        raise IdReutilizado()
    if datos["estado"] == "PENDING":
        raise EnProceso()
    return datos["resultado"]


def guardar(tx_id, firma, resultado: dict):
    hecho = {"estado": "DONE", "huella": firma, "resultado": resultado}
    get_cache().set(_clave(tx_id), json.dumps(hecho, default=str), ex=TTL)


def liberar(tx_id):
    """Si decidir falla, borra la reserva para que el reintento pueda decidir."""
    get_cache().delete(_clave(tx_id))
