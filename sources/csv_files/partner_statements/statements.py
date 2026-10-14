"""Arma los extractos de cada socio por día e inyecta sus defectos.

Defectos que pide el enunciado para los archivos de los socios, todos con
porcentaje configurable (config.py) y semilla fija:

- Transacciones faltantes: el socio no reporta una operación nuestra.
- Operaciones que solo tiene el socio: faltante en PagoSeguro.
- Montos redondeados: el socio redondea a la unidad (o a la decena si el
  monto ya era entero), así que la diferencia pasa la tolerancia de 0,01.
- Fechas en otra zona horaria: no es un porcentaje, es el formato de dos
  socios (partners.py).
- Archivos reenviados con correcciones: el socio manda un v2 del mismo día
  que repone los faltantes y corrige los redondeos del v1.
- Registros de control que no cuadran: el control declara otra cantidad
  u otro total que el detalle.

Además del archivo, cada defecto queda en el reporte con la diferencia que
la conciliación debería encontrar en la última versión de cada día. Es la
hoja de respuestas para probar la conciliación.
"""

import random
import uuid
from dataclasses import dataclass, replace
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from sources.csv_files.partner_statements.money import paso
from sources.csv_files.partner_statements.partners import SOCIOS, Extracto, Registro

NAMESPACE = uuid.UUID("5e1f2c3d-4b5a-6978-8a9b-0c1d2e3f4a5b")
TOLERANCIA = Decimal("0.01")

# Tipos de diferencia de la conciliación (los tres del enunciado).
FALTANTE_EN_SOCIO = "MISSING_IN_PARTNER"
FALTANTE_EN_PAGOSEGURO = "MISSING_IN_PAGOSEGURO"
DIFERENCIA_MONTO = "AMOUNT_MISMATCH"


@dataclass(frozen=True)
class Porcentajes:
    faltantes: float = 0
    extras: float = 0
    redondeo: float = 0
    reenvio: float = 0
    control: float = 0


class Generador:
    def __init__(self, semilla, porcentajes: Porcentajes):
        self.rng = random.Random(f"{semilla}:extractos")
        self.pct = porcentajes
        self.defectos = []
        self.diferencias = []
        self._refs = {}

    def _toca(self, porcentaje):
        return self.rng.random() * 100 < porcentaje

    def _ref_socio(self, socio):
        self._refs[socio.nombre] = self._refs.get(socio.nombre, 0) + 1
        return f"{socio.prefijo}{self._refs[socio.nombre]:09d}"

    def _anotar(self, defecto, socio, dia, version, referencia, detalle):
        self.defectos.append({
            "defect": defecto, "partner": socio.nombre, "day": dia.isoformat(),
            "version": version, "reference": referencia, "detail": detalle,
        })

    def _diferencia(self, tipo, socio, dia, referencia, moneda, nuestro, del_socio):
        self.diferencias.append({
            "type": tipo, "partner": socio.nombre, "day": dia.isoformat(),
            "reference": referencia, "currency": moneda,
            "pagoseguro_amount": None if nuestro is None else str(nuestro),
            "partner_amount": None if del_socio is None else str(del_socio),
        })

    # --- Defectos por registro ----------------------------------------------

    @staticmethod
    def redondeado(registro):
        """El monto redondeado a la unidad, o a la decena si ya era entero.

        Devuelve None si ni así cambia más que la tolerancia.
        """
        for unidad in (Decimal(1), Decimal(10)):
            nuevo = (registro.monto / unidad).quantize(Decimal(1), ROUND_HALF_UP) * unidad
            if nuevo > 0 and abs(nuevo - registro.monto) > TOLERANCIA:
                return replace(registro, monto=nuevo.quantize(paso(registro.moneda)))
        return None

    def _extra(self, socio, base, dia, n):
        """Una operación que el socio reporta y PagoSeguro no tiene."""
        ref = str(uuid.uuid5(NAMESPACE, f"extra:{socio.nombre}:{dia}:{n}"))
        # Unos minutos antes de una operación real del mismo día, sin
        # cambiar de día en la zona del socio.
        fecha = base.fecha - timedelta(seconds=self.rng.randint(1, 600))
        if socio.dia_de(fecha) != dia:
            fecha = base.fecha
        return replace(base, ref_pagoseguro=ref, ref_socio=self._ref_socio(socio), fecha=fecha)

    def _control(self, socio, registros):
        """Control que no cuadra: cambia la cantidad o el total."""
        cantidad, total = socio.control_real(registros)
        if self.rng.random() < 0.5:
            cantidad = cantidad + 1 if cantidad == 0 else cantidad + self.rng.choice((-1, 1))
        else:
            total += Decimal(self.rng.randint(100, 99_999))
        return cantidad, total

    # --- Armado --------------------------------------------------------------

    def _dias(self, operaciones, socio):
        """Todos los días del periodo en la zona del socio, aunque no tenga
        operaciones: un socio real manda el archivo aunque venga vacío."""
        if not operaciones:
            return []
        primero = socio.dia_de(operaciones[0].fecha)
        ultimo = socio.dia_de(operaciones[-1].fecha)
        return [primero + timedelta(days=i) for i in range((ultimo - primero).days + 1)]

    def construir(self, operaciones):
        """Devuelve [(socio, extracto)] con todas las versiones de cada día."""
        archivos = []
        for socio in SOCIOS:
            por_dia = {}
            for op in operaciones:
                if socio.ve(op):
                    por_dia.setdefault(socio.dia_de(op.fecha), []).append(op)

            for dia in self._dias(operaciones, socio):
                archivos += self._dia(socio, dia, por_dia.get(dia, []))
        return archivos

    def _dia(self, socio, dia, operaciones):
        correctos = [
            Registro(
                ref_pagoseguro=op.id, ref_socio=self._ref_socio(socio), tipo=op.tipo,
                monto=op.monto, moneda=op.moneda, fecha=op.fecha, comercio=op.comercio,
            )
            for op in operaciones
        ]

        v1, faltantes, redondeados = [], [], {}
        for r in correctos:
            if self._toca(self.pct.faltantes):
                faltantes.append(r)
                self._anotar("MISSING_RECORD", socio, dia, 1, r.ref_pagoseguro,
                             "el socio no reporta la operación")
                continue
            if self._toca(self.pct.redondeo):
                nuevo = self.redondeado(r)
                if nuevo:
                    redondeados[r.ref_pagoseguro] = (r, nuevo)
                    self._anotar("ROUNDED_AMOUNT", socio, dia, 1, r.ref_pagoseguro,
                                 f"{r.monto} -> {nuevo.monto} {r.moneda}")
                    v1.append(nuevo)
                    continue
            v1.append(r)

        extras = []
        for r in correctos:
            if self._toca(self.pct.extras):
                extra = self._extra(socio, r, dia, len(extras))
                extras.append(extra)
                self._anotar("EXTRA_RECORD", socio, dia, 1, extra.ref_pagoseguro,
                             "operación que PagoSeguro no tiene")

        por_fecha = lambda rs: sorted(rs, key=lambda r: (r.fecha, r.ref_socio))  # noqa: E731
        versiones = [por_fecha(v1 + extras)]

        # El reenvío solo tiene sentido si hay algo que corregir.
        corregido = bool(faltantes or redondeados) and self._toca(self.pct.reenvio)
        if corregido:
            versiones.append(por_fecha(correctos + extras))
            for d in self.defectos:
                if (d["partner"], d["day"]) == (socio.nombre, dia.isoformat()) and \
                        d["defect"] in ("MISSING_RECORD", "ROUNDED_AMOUNT"):
                    d["corrected_in_v2"] = True

        resultado = []
        for numero, registros in enumerate(versiones, start=1):
            extracto = Extracto(socio.nombre, dia, numero, registros)
            if self._toca(self.pct.control):
                extracto.control = self._control(socio, registros)
                real = socio.control_real(registros)
                self._anotar("BAD_CONTROL_TOTALS", socio, dia, numero, None,
                             f"declara {extracto.control[0]} registros y total "
                             f"{extracto.control[1]}; el detalle tiene {real[0]} y {real[1]}")
            resultado.append((socio, extracto))

        # Lo que la conciliación debe encontrar, contra la última versión.
        if not corregido:
            for r in faltantes:
                self._diferencia(FALTANTE_EN_SOCIO, socio, dia, r.ref_pagoseguro,
                                 r.moneda, r.monto, None)
            for original, nuevo in redondeados.values():
                self._diferencia(DIFERENCIA_MONTO, socio, dia, original.ref_pagoseguro,
                                 original.moneda, original.monto, nuevo.monto)
        for r in extras:
            self._diferencia(FALTANTE_EN_PAGOSEGURO, socio, dia, r.ref_pagoseguro,
                             r.moneda, None, r.monto)
        return resultado
