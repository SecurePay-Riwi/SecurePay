"""Extracción: lee los CSV de Kaggle y toma una muestra fija.

Los CSV pesan cientos de MB (PaySim tiene 6,3 millones de filas), así que
se leen de a una fila, sin cargarlos en memoria. La muestra es estratificada:
se pide una cantidad exacta de fraudes y de transacciones normales, cada
grupo con su propio azar. El muestreo es por reservorio (algoritmo R) y usa
solo random(), que da la misma secuencia en cualquier sistema operativo.
"""

import csv
import hashlib
from collections import namedtuple
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from db.datasets.config import (
    CATEGORIA_FRAUDTEST,
    TIPO_PAYSIM,
    nuevo_rng,
)

CENTAVOS = Decimal("0.01")
# La columna transacciones.amount es Numeric(12, 2).
MONTO_MAX = 9_999_999_999.99

# `titular` es quien hace la operación en el dataset: la cuenta origen en
# PaySim (nameOrig) y la tarjeta en Sparkov (cc_num). Cada titular queda
# ligado a un solo usuario del seed.
FilaPaySim = namedtuple("FilaPaySim", "indice step tipo monto es_fraude titular")
FilaFraudTest = namedtuple("FilaFraudTest", "indice fecha categoria monto es_fraude titular")


@dataclass
class Muestra:
    """Filas elegidas de un dataset y lo que pasó al leerlo."""

    dataset: str
    pedidas_fraude: int = 0
    pedidas_normales: int = 0
    leidas: int = 0
    descartadas: int = 0
    disponibles_fraude: int = 0
    disponibles_normales: int = 0
    filas: list = field(default_factory=list)

    @property
    def fraude(self):
        return sum(1 for f in self.filas if f.es_fraude)


class Reservorio:
    """Muestra uniforme de k elementos de una secuencia de largo desconocido."""

    def __init__(self, k, rng):
        self.k = k
        self.rng = rng
        self.vistos = 0
        self.items = []

    def agregar(self, item):
        self.vistos += 1
        if len(self.items) < self.k:
            self.items.append(item)
        else:
            j = int(self.rng.random() * self.vistos)
            if j < self.k:
                self.items[j] = item


def sha256_archivo(ruta):
    with open(ruta, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def _monto_valido(texto):
    """Mayor que cero y dentro de lo que cabe en la columna amount."""
    try:
        valor = float(texto)
    except ValueError:
        return False
    # Con nan o inf las comparaciones dan False.
    return 0 < valor <= MONTO_MAX


def _a_decimal(texto):
    return Decimal(texto).quantize(CENTAVOS, rounding=ROUND_HALF_UP)


def _pedidas(total, fraude_pct):
    pedidas_fraude = round(total * fraude_pct / 100)
    return pedidas_fraude, total - pedidas_fraude


def muestrear_paysim(ruta, total, fraude_pct):
    columnas = {
        "step": "step", "tipo": "type", "monto": "amount", "fraude": "isFraud",
        "titular": "nameOrig",
    }

    def valida(fila, pos):
        return fila[pos["tipo"]] in TIPO_PAYSIM and _monto_valido(fila[pos["monto"]])

    muestra, elegidas, pos = _muestrear(
        ruta, "paysim", total, fraude_pct, columnas, valida
    )
    muestra.filas = [
        FilaPaySim(
            indice=indice,
            step=int(fila[pos["step"]]),
            tipo=fila[pos["tipo"]],
            monto=_a_decimal(fila[pos["monto"]]),
            es_fraude=es_fraude,
            titular=fila[pos["titular"]],
        )
        for indice, fila, es_fraude in elegidas
    ]
    return muestra


def muestrear_fraudtest(ruta, total, fraude_pct):
    columnas = {
        "fecha": "trans_date_trans_time",
        "categoria": "category",
        "monto": "amt",
        "fraude": "is_fraud",
        "titular": "cc_num",
    }

    def valida(fila, pos):
        return (
            fila[pos["categoria"]] in CATEGORIA_FRAUDTEST
            and _monto_valido(fila[pos["monto"]])
        )

    muestra, elegidas, pos = _muestrear(
        ruta, "fraudtest", total, fraude_pct, columnas, valida
    )
    # La fecha se convierte solo en las filas elegidas: hacerlo en las 555 mil
    # sería lento y no hace falta.
    muestra.filas = [
        FilaFraudTest(
            indice=indice,
            fecha=datetime.strptime(fila[pos["fecha"]], "%Y-%m-%d %H:%M:%S"),
            categoria=fila[pos["categoria"]],
            monto=_a_decimal(fila[pos["monto"]]),
            es_fraude=es_fraude,
            titular=fila[pos["titular"]],
        )
        for indice, fila, es_fraude in elegidas
    ]
    return muestra


def _muestrear(ruta, dataset, total, fraude_pct, columnas, valida):
    """Igual que _muestrear, pero `columnas` mapea un nombre corto -> cabecera."""
    pedidas_fraude, pedidas_normales = _pedidas(total, fraude_pct)
    muestra = Muestra(
        dataset=dataset,
        pedidas_fraude=pedidas_fraude,
        pedidas_normales=pedidas_normales,
    )
    fraudes = Reservorio(pedidas_fraude, nuevo_rng(dataset, "muestreo_fraude"))
    normales = Reservorio(pedidas_normales, nuevo_rng(dataset, "muestreo_normales"))

    with open(ruta, newline="", encoding="utf-8") as f:
        lector = csv.reader(f)
        cabecera = next(lector)
        pos = {nombre: cabecera.index(col) for nombre, col in columnas.items()}

        for indice, fila in enumerate(lector):
            muestra.leidas += 1
            try:
                if not valida(fila, pos):
                    muestra.descartadas += 1
                    continue
                es_fraude = fila[pos["fraude"]] == "1"
            except IndexError:
                muestra.descartadas += 1
                continue

            destino = fraudes if es_fraude else normales
            destino.agregar((indice, fila, es_fraude))

    muestra.disponibles_fraude = fraudes.vistos
    muestra.disponibles_normales = normales.vistos
    elegidas = fraudes.items + normales.items
    # En el orden del archivo: ambos datasets vienen ordenados por tiempo.
    elegidas.sort(key=lambda x: x[0])
    return muestra, elegidas, pos
