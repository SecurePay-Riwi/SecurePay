"""Montos y monedas: tasas de cambio y precisión de cada moneda."""

import json
from decimal import ROUND_HALF_UP, Decimal

from generators.config import TASAS_FILE
from shared.config import MONEDA_DECIMALES


def cargar_tasas(ruta=TASAS_FILE):
    """Lee las tasas guardadas: unidades de cada moneda por 1 USD."""
    # parse_float=Decimal lee 0.88286 como Decimal exacto, sin pasar por
    # float, que lo guardaría como 0.88285999999999997...
    datos = json.loads(ruta.read_text(encoding="utf-8"), parse_float=Decimal)
    return {moneda: Decimal(tasa) for moneda, tasa in datos["tasas"].items()}


def paso(moneda):
    """La unidad más pequeña de la moneda: 0.01, o 1 para el yen."""
    return Decimal(1).scaleb(-MONEDA_DECIMALES[moneda])


def redondear(monto, moneda):
    """Deja el monto con los decimales que admite su moneda."""
    return Decimal(monto).quantize(paso(moneda), rounding=ROUND_HALF_UP)


def desde_usd(usd, moneda, tasas):
    """Convierte un monto en USD a la moneda de la cuenta."""
    return redondear(Decimal(str(usd)) * tasas[moneda], moneda)


def a_usd(monto, moneda, tasas):
    """Convierte un monto de su moneda a USD (sin redondear)."""
    return Decimal(monto) / tasas[moneda]
