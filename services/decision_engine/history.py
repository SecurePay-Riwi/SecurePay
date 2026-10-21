"""Historial de movimientos por cuenta en Valkey, ordenado por la hora
del evento. Lo leen las reglas que miran el pasado de la cuenta.

Dos sorted sets por cuenta, con la transaction_date en milisegundos como
puntaje (un evento que llega tarde queda en su lugar real, no al final):

- `out:{cuenta}`: lo que sale de la cuenta (P2P, QR y retiro).
  Miembro `id|tipo|monto`. Lo usan la velocidad (10 min) y, más
  adelante, el fraccionamiento (24 h).
- `in:{cuenta}`: las transferencias P2P que entran. Miembro
  `id|remitente`. Lo usa la regla de cuenta mula (30 min).

Una recarga no se guarda: no viene de otra cuenta ni sale dinero.

Se guardan los intentos, sin importar la decisión: el historial se
escribe antes de decidir, en una sola llamada (decidido por Jorge el
2026-10-21). Que varias personas intenten mandar dinero a una cuenta, o
que una cuenta intente muchas transferencias, ya es la señal.

El monto va en la moneda de la cuenta: todas las transacciones de una
cuenta usan su moneda, así que las sumas cuadran. Pasarlo a USD llega
cuando el motor lea la tabla de tasas.
"""

import os
from dataclasses import dataclass

from shared.cache import get_cache

SALIDAS_HORAS = int(os.getenv("HISTORY_OUT_HOURS", "24"))
ENTRADAS_MIN = int(os.getenv("HISTORY_IN_MINUTES", "60"))

if SALIDAS_HORAS <= 0 or ENTRADAS_MIN <= 0:
    raise ValueError("La retención del historial debe ser positiva.")

SALIDAS_MS = SALIDAS_HORAS * 3600 * 1000
ENTRADAS_MS = ENTRADAS_MIN * 60 * 1000

# Todo en un script para que dos peticiones de la misma cuenta no se
# pisen: Valkey ejecuta un script completo antes de atender otro comando.
# Una sola clave por script: en ElastiCache Serverless dos claves pueden
# vivir en nodos distintos.
# KEYS[1] = out:{cuenta} o in:{cuenta}
# ARGV = miembro, hora del evento (ms), retención (ms), retención (s),
#        devolver el historial (1) o no (0)
_REGISTRAR = """
redis.call('ZADD', KEYS[1], ARGV[2], ARGV[1])
local ultimo = redis.call('ZRANGE', KEYS[1], -1, -1, 'WITHSCORES')
local corte = tonumber(ultimo[2]) - tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', string.format('(%.0f', corte))
redis.call('EXPIRE', KEYS[1], ARGV[4])
if ARGV[5] == '1' then
  return redis.call('ZRANGE', KEYS[1], 0, -1, 'WITHSCORES')
end
return {}
"""

_script = None


@dataclass(frozen=True)
class Salida:
    id: str
    tipo: str
    monto: str
    t: int  # hora del evento en ms


@dataclass(frozen=True)
class Entrada:
    id: str
    remitente: str
    t: int


def clave_salidas(cuenta_id) -> str:
    return f"out:{cuenta_id}"


def clave_entradas(cuenta_id) -> str:
    return f"in:{cuenta_id}"


def a_ms(fecha) -> int:
    return int(fecha.timestamp() * 1000)


def _registrar(clave, miembro, fecha, retencion_ms, devolver):
    global _script
    if _script is None:
        _script = get_cache().register_script(_REGISTRAR)

    return _script(
        keys=[clave],
        args=[miembro, a_ms(fecha), retencion_ms, retencion_ms // 1000,
              1 if devolver else 0],
    )


def _pares(crudo):
    """La respuesta de Valkey alterna miembro y puntaje."""
    return zip(crudo[0::2], crudo[1::2])


def registrar_salida(cuenta_id, tx_id, tipo, monto, fecha) -> list[Salida]:
    """Guarda lo que sale de la cuenta y devuelve todas sus salidas
    retenidas, en orden cronológico real."""
    miembro = f"{tx_id}|{tipo}|{monto}"
    crudo = _registrar(
        clave_salidas(cuenta_id), miembro, fecha, SALIDAS_MS, devolver=True
    )

    salidas = []
    for m, t in _pares(crudo):
        id_, tipo_, monto_ = m.split("|")
        salidas.append(Salida(id_, tipo_, monto_, int(float(t))))
    return salidas


def registrar_entrada(cuenta_id, tx_id, remitente_id, fecha) -> None:
    """Guarda una transferencia que entra a la cuenta. No devuelve nada:
    las reglas se evalúan sobre la cuenta que mueve el dinero."""
    _registrar(
        clave_entradas(cuenta_id),
        f"{tx_id}|{remitente_id}",
        fecha,
        ENTRADAS_MS,
        devolver=False,
    )


def entradas(cuenta_id) -> list[Entrada]:
    """Transferencias que entraron a la cuenta, en orden cronológico."""
    crudo = get_cache().zrange(clave_entradas(cuenta_id), 0, -1, withscores=True)
    resultado = []
    for m, t in crudo:
        id_, remitente = m.split("|")
        resultado.append(Entrada(id_, remitente, int(t)))
    return resultado
