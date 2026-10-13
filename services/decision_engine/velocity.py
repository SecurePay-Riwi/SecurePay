"""Historial de transferencias por cuenta en Valkey, ordenado por la hora
del evento.

Cada cuenta tiene un sorted set `vel:{cuenta}` con el id de la
transacción como miembro y su transaction_date (en milisegundos) como
puntaje. Valkey lo mantiene ordenado por puntaje, así que un evento que
llega tarde queda en su lugar real y no al final.
"""

import os
from bisect import bisect_left, bisect_right

from shared.cache import get_cache

VENTANA_MIN = int(os.getenv("VELOCITY_WINDOW_MINUTES", "10"))
LIMITE = int(os.getenv("VELOCITY_LIMIT", "5"))
# Cuánto historial se guarda por cuenta, medido desde el evento más
# reciente. Un evento que llegue más tarde que esto se evalúa con
# historial incompleto.
HISTORIAL_HORAS = int(os.getenv("VELOCITY_HISTORY_HOURS", "24"))

if VENTANA_MIN <= 0 or LIMITE <= 0 or HISTORIAL_HORAS <= 0:
    raise ValueError("Los parámetros de velocidad deben ser positivos.")

VENTANA_MS = VENTANA_MIN * 60 * 1000
HISTORIAL_MS = HISTORIAL_HORAS * 3600 * 1000

# Todo en un script para que dos peticiones de la misma cuenta no se
# pisen: Valkey ejecuta un script completo antes de atender otro comando.
# KEYS[1] = vel:{cuenta}
# ARGV = id, hora del evento (ms), ventana (ms), historial (ms), historial (s)
_REGISTRAR = """
local t = tonumber(ARGV[2])
local ventana = tonumber(ARGV[3])
redis.call('ZADD', KEYS[1], t, ARGV[1])
local ultimo = redis.call('ZRANGE', KEYS[1], -1, -1, 'WITHSCORES')
local corte = tonumber(ultimo[2]) - tonumber(ARGV[4])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', string.format('(%.0f', corte))
redis.call('EXPIRE', KEYS[1], ARGV[5])
return redis.call('ZRANGEBYSCORE', KEYS[1],
    string.format('%.0f', t - ventana), string.format('%.0f', t + ventana),
    'WITHSCORES')
"""

_script = None


def _clave(cuenta_id):
    return f"vel:{cuenta_id}"


def _registrar():
    global _script
    if _script is None:
        _script = get_cache().register_script(_REGISTRAR)
    return _script


def a_ms(fecha) -> int:
    return int(fecha.timestamp() * 1000)


def max_en_ventana(horas: list[int], t: int, ventana: int = VENTANA_MS) -> int:
    """Mayor número de transferencias dentro de una ventana de `ventana` ms
    que contenga a t. `horas` viene ordenada e incluye a t.

    Basta probar las ventanas que empiezan en cada evento entre t - ventana
    y t: cualquier otra se puede correr hasta un evento sin perder ninguno.
    """
    mejor = 0
    desde = bisect_left(horas, t - ventana)
    hasta = bisect_right(horas, t)

    for inicio in horas[desde:hasta]:
        dentro = bisect_right(horas, inicio + ventana) - bisect_left(horas, inicio)
        mejor = max(mejor, dentro)

    return mejor


def registrar_y_contar(cuenta_id, tx_id, fecha) -> int:
    """Guarda la transferencia en el historial de la cuenta y devuelve
    cuántas hay en la ventana más cargada de las que la contienen.

    Si llega tarde, cuenta también las transferencias posteriores que ya
    se habían procesado, porque en el tiempo real van después de ella.
    """
    t = a_ms(fecha)
    vecinos = _registrar()(
        keys=[_clave(cuenta_id)],
        args=[str(tx_id), t, VENTANA_MS, HISTORIAL_MS, HISTORIAL_MS // 1000],
    )
    # La respuesta alterna miembro y puntaje, ya ordenada por puntaje.
    horas = [int(float(p)) for p in vecinos[1::2]]
    return max_en_ventana(horas, t)


def historial(cuenta_id) -> list[str]:
    """Ids de la cuenta en orden cronológico real (por hora del evento)."""
    return get_cache().zrange(_clave(cuenta_id), 0, -1)
