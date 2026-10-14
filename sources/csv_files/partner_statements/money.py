"""Precisión de cada moneda.

Es una copia mínima de lo que hace generators/money.py: los extractos no
importan nada del generador, para poder moverse solos a su propio repo
(ver el plan de separación). Los decimales por moneda sí vienen de
shared/, que será una librería común.
"""

from decimal import ROUND_HALF_UP, Decimal

from shared.config import MONEDA_DECIMALES


def paso(moneda):
    """La unidad más pequeña de la moneda: 0.01, o 1 para el yen."""
    return Decimal(1).scaleb(-MONEDA_DECIMALES[moneda])


def redondear(monto, moneda):
    """Deja el monto con los decimales que admite su moneda."""
    return Decimal(monto).quantize(paso(moneda), rounding=ROUND_HALF_UP)
