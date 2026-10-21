"""Regla de velocidad: más de LIMITE transferencias salientes en
VENTANA_MIN minutos desde la misma cuenta.

Cuenta sobre el historial de salidas de la cuenta (history.py), que
está ordenado por la hora del evento: un evento que llega tarde se cuenta
en su lugar real.
"""

import os
from bisect import bisect_left, bisect_right

VENTANA_MIN = int(os.getenv("VELOCITY_WINDOW_MINUTES", "10"))
LIMITE = int(os.getenv("VELOCITY_LIMIT", "5"))

if VENTANA_MIN <= 0 or LIMITE <= 0:
    raise ValueError("Los parámetros de velocidad deben ser positivos.")

VENTANA_MS = VENTANA_MIN * 60 * 1000

# Solo las transferencias entre cuentas cuentan: un pago QR va a un
# comercio y un retiro sale a efectivo (bitácora 3.7).
TIPOS = {"P2P"}


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


def contar(salidas, t: int) -> int:
    """Transferencias en la ventana más cargada de las que contienen a t.

    `salidas` es el historial de la cuenta ya ordenado (incluye la
    transferencia que se está evaluando). Si llegó tarde, cuenta también
    las posteriores ya procesadas, porque en el tiempo real van después.
    """
    horas = [s.t for s in salidas if s.tipo in TIPOS]
    return max_en_ventana(horas, t)
