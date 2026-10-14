"""Pruebas de los extractos de los socios. No usan base de datos."""

import json
import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from sources.csv_files.partner_statements.money import redondear
from sources.csv_files.partner_statements.output import SalidaLocal, ruta_relativa
from sources.csv_files.partner_statements.partners import (
    SOCIOS,
    BancoAndino,
    Extracto,
    RedCorresponsales,
    Registro,
    socio_de,
)
from sources.csv_files.partner_statements.reader import Operacion, leer
from sources.csv_files.partner_statements.statements import (
    DIFERENCIA_MONTO,
    FALTANTE_EN_PAGOSEGURO,
    FALTANTE_EN_SOCIO,
    TOLERANCIA,
    Generador,
    Porcentajes,
)

INICIO = datetime(2026, 10, 1, tzinfo=timezone.utc)
# Tipo y canal de las operaciones que ve algún socio.
CAMINOS = [("RECARGA", "APP"), ("RECARGA", "WEB"), ("RECARGA", "CORRESPONSAL"),
           ("RETIRO", "CORRESPONSAL"), ("RETIRO", "CAJERO"), ("QR", "APP")]
MONTOS = {"COP": (1_000, 2_000_000), "USD": (1, 500), "EUR": (1, 500), "JPY": (100, 70_000)}


def operaciones(n=2_000, dias=5, semilla=1):
    rng = random.Random(semilla)
    ops = []
    for i in range(n):
        tipo, canal = rng.choice(CAMINOS)
        moneda = rng.choice(list(MONTOS))
        ops.append(Operacion(
            id=f"tx-{i:05d}", tipo=tipo, canal=canal, moneda=moneda,
            monto=redondear(Decimal(str(rng.uniform(*MONTOS[moneda]))), moneda),
            fecha=INICIO + timedelta(seconds=rng.randint(0, dias * 86_400)),
            comercio=f"merchant-{rng.randint(1, 9)}" if tipo == "QR" else None,
        ))
    return sorted(ops, key=lambda o: (o.fecha, o.id))


def generar(ops, semilla=42, **pct):
    g = Generador(semilla, Porcentajes(**pct))
    return g, g.construir(ops)


def ultimas_versiones(archivos):
    """(socio, día) -> el extracto de la última versión, leído de su texto."""
    ultimas = {}
    for socio, ext in archivos:
        ultimas[(socio.nombre, ext.dia)] = (socio, ext)
    return {k: s.leer(s.escribir(e)) for k, (s, e) in ultimas.items()}


def conciliar(ops, leidos):
    """Conciliación mínima por referencia y monto, para comprobar el reporte."""
    nuestras = {o.id: o for o in ops}
    del_socio = {r.ref_pagoseguro: r for leido in leidos.values() for r in leido.registros}
    diferencias = set()
    for ref, op in nuestras.items():
        if ref not in del_socio:
            diferencias.add((FALTANTE_EN_SOCIO, ref))
        elif abs(del_socio[ref].monto - op.monto) > TOLERANCIA:
            diferencias.add((DIFERENCIA_MONTO, ref))
    for ref in del_socio.keys() - nuestras.keys():
        diferencias.add((FALTANTE_EN_PAGOSEGURO, ref))
    return diferencias


# --- Formatos ----------------------------------------------------------------


@pytest.mark.parametrize("socio", SOCIOS, ids=lambda s: s.nombre)
def test_cada_formato_se_lee_de_vuelta(socio):
    ops = [o for o in operaciones(300) if socio.ve(o)][:20]
    registros = [
        Registro(o.id, f"{socio.prefijo}{i:09d}", o.tipo, o.monto, o.moneda, o.fecha, o.comercio)
        for i, o in enumerate(ops)
    ]
    extracto = Extracto(socio.nombre, socio.dia_de(ops[0].fecha), 1, registros)

    leido = socio.leer(socio.escribir(extracto))

    assert leido.control == socio.control_real(registros)
    assert len(leido.registros) == len(registros)
    for original, vuelta in zip(registros, leido.registros):
        assert vuelta.ref_pagoseguro == original.ref_pagoseguro
        assert vuelta.ref_socio == original.ref_socio
        assert vuelta.monto == original.monto
        assert vuelta.moneda == original.moneda
        assert vuelta.tipo == original.tipo
        # Los formatos no guardan microsegundos.
        assert vuelta.fecha == original.fecha.replace(microsecond=0)


def test_ancho_fijo_tiene_largo_constante():
    socio = RedCorresponsales()
    ops = [o for o in operaciones(300) if socio.ve(o)][:10]
    registros = [Registro(o.id, f"RC{i:09d}", o.tipo, o.monto, o.moneda, o.fecha) for i, o in enumerate(ops)]
    texto = socio.escribir(Extracto(socio.nombre, socio.dia_de(ops[0].fecha), 1, registros))
    detalle = [linea for linea in texto.splitlines() if linea.startswith("D")]
    assert {len(linea) for linea in detalle} == {88}


def test_cada_operacion_tiene_un_solo_socio():
    for op in operaciones(500):
        assert sum(s.ve(op) for s in SOCIOS) == 1
    p2p = Operacion("x", "P2P", "APP", Decimal(1), "USD", INICIO)
    assert socio_de(p2p) is None


def test_el_dia_es_el_de_la_zona_del_socio():
    # 03:00 UTC del 2 de octubre son las 22:00 del 1 de octubre en Bogotá.
    fecha = datetime(2026, 10, 2, 3, 0, tzinfo=timezone.utc)
    assert BancoAndino().dia_de(fecha).isoformat() == "2026-10-02"
    assert RedCorresponsales().dia_de(fecha).isoformat() == "2026-10-01"


# --- Lectura de la salida del generador ---------------------------------------


def _tx(id, tipo="RECARGA", canal="APP", monto="10.00", moneda="USD"):
    return {"kind": "transaction", "endpoint": "/transactions", "body": {
        "id": id, "type": tipo, "channel": canal, "amount": monto, "currency": moneda,
        "merchant_id": None, "transaction_date": "2026-10-01T10:00:00+00:00"}}


def _escribir_jsonl(ruta, filas):
    ruta.write_text("".join(json.dumps(f) + "\n" for f in filas), encoding="utf-8")


def test_lee_solo_lo_que_ve_un_socio(tmp_path):
    carpeta = tmp_path / "instance-0"
    carpeta.mkdir()
    _escribir_jsonl(carpeta / "events.jsonl", [
        _tx("a"),
        _tx("a"),  # reenvío del core: cuenta una vez
        _tx("b", tipo="P2P"),  # interna: ningún socio la ve
        _tx("c", monto="88.910"),  # decimales de más: mismo valor
        _tx("d"),  # rechazada por el motor
        {"kind": "security", "endpoint": "/security-events", "body": {"id": "s"}},
    ])
    _escribir_jsonl(carpeta / "labels.jsonl", [
        {"id": "a", "response": {"status": 200, "decision": "APPROVE"}},
        {"id": "d", "response": {"status": 200, "decision": "REJECT"}},
    ])

    ops = leer(tmp_path)

    assert [o.id for o in ops] == ["a", "c"]
    assert ops[1].monto == Decimal("88.91")


def test_sin_salida_del_generador_avisa(tmp_path):
    with pytest.raises(FileNotFoundError, match="generators"):
        leer(tmp_path)


# --- Defectos ----------------------------------------------------------------


def test_sin_defectos_cada_operacion_aparece_una_vez():
    ops = operaciones()
    g, archivos = generar(ops)

    refs = [r.ref_pagoseguro for _, e in archivos for r in e.registros]
    assert sorted(refs) == sorted(o.id for o in ops)
    assert all(e.version == 1 and e.control is None for _, e in archivos)
    assert g.defectos == [] and g.diferencias == []


def test_hay_archivo_por_socio_y_dia_aunque_venga_vacio():
    ops = operaciones(n=50, dias=10)
    _, archivos = generar(ops)
    for socio in SOCIOS:
        dias = [e.dia for s, e in archivos if s is socio]
        assert len(dias) == len(set(dias))
        assert (max(dias) - min(dias)).days + 1 == len(dias)


def test_misma_semilla_mismos_archivos():
    ops = operaciones()
    pct = dict(faltantes=5, extras=5, redondeo=5, reenvio=50, control=20)
    texto = lambda archivos: [s.escribir(e) for s, e in archivos]  # noqa: E731
    assert texto(generar(ops, **pct)[1]) == texto(generar(ops, **pct)[1])
    assert texto(generar(ops, **pct)[1]) != texto(generar(ops, semilla=7, **pct)[1])


def test_proporcion_de_defectos():
    ops = operaciones(n=5_000)
    g, _ = generar(ops, faltantes=4, extras=2, redondeo=6)
    por_tipo = {t: sum(d["defect"] == t for d in g.defectos)
                for t in ("MISSING_RECORD", "EXTRA_RECORD", "ROUNDED_AMOUNT")}
    assert 150 <= por_tipo["MISSING_RECORD"] <= 250  # ~200
    assert 60 <= por_tipo["EXTRA_RECORD"] <= 140  # ~100
    assert 220 <= por_tipo["ROUNDED_AMOUNT"] <= 380  # ~300 menos los que no cambian


def test_el_reporte_es_lo_que_encuentra_la_conciliacion():
    ops = operaciones()
    g, archivos = generar(ops, faltantes=5, extras=3, redondeo=5, reenvio=30, control=10)

    esperado = {(d["type"], d["reference"]) for d in g.diferencias}
    assert esperado == conciliar(ops, ultimas_versiones(archivos))
    assert {t for t, _ in esperado} == {FALTANTE_EN_SOCIO, FALTANTE_EN_PAGOSEGURO, DIFERENCIA_MONTO}


def test_montos_redondeados_pasan_la_tolerancia():
    ops = operaciones()
    g, _ = generar(ops, redondeo=10)
    montos = [d for d in g.diferencias if d["type"] == DIFERENCIA_MONTO]
    assert montos
    for d in montos:
        assert abs(Decimal(d["pagoseguro_amount"]) - Decimal(d["partner_amount"])) > TOLERANCIA
        assert Decimal(d["partner_amount"]) % 1 == 0


def test_el_reenvio_corrige_faltantes_y_redondeos():
    ops = operaciones()
    g, archivos = generar(ops, faltantes=5, redondeo=5, reenvio=100)

    v2 = [(s, e) for s, e in archivos if e.version == 2]
    assert v2
    # Todo día con faltantes o redondeos se reenvió, y el v2 ya cuadra.
    assert all(d.get("corrected_in_v2") for d in g.defectos)
    assert g.diferencias == []
    assert conciliar(ops, ultimas_versiones(archivos)) == set()


def test_control_que_no_cuadra():
    ops = operaciones(n=300)
    g, archivos = generar(ops, control=100)
    for socio, extracto in archivos:
        leido = socio.leer(socio.escribir(extracto))
        assert leido.control != socio.control_real(leido.registros)
    assert len([d for d in g.defectos if d["defect"] == "BAD_CONTROL_TOTALS"]) == len(archivos)


# --- Salida ------------------------------------------------------------------


def test_ruta_particionada_por_socio_y_dia(tmp_path):
    ops = operaciones(n=100)
    _, archivos = generar(ops)
    socio, extracto = archivos[0]
    relativa = ruta_relativa(socio, extracto)
    assert relativa.startswith(f"{socio.nombre}/fecha={extracto.dia:%Y-%m-%d}/")
    assert relativa.endswith(f"_v1.{socio.extension}")

    salida = SalidaLocal(tmp_path / "extractos")
    salida.guardar(relativa, socio.escribir(extracto))
    # Fin de línea "\n" aun en Windows.
    assert b"\r\n" not in (tmp_path / "extractos" / relativa).read_bytes()


def test_sube_a_la_capa_raw(monkeypatch):
    subidos = []

    class S3Falso:
        def put_object(self, **kwargs):
            subidos.append(kwargs)

    monkeypatch.setattr("shared.aws.cliente", lambda *a, **k: S3Falso())
    from sources.csv_files.partner_statements.output import SalidaS3

    SalidaS3("pagoseguro-datalake", "raw/extractos").guardar(
        "qr_pagos/fecha=2026-10-01/qr_pagos_20261001_v1.txt", "#CTRL|2026-10-01|0|0\n"
    )
    assert subidos[0]["Bucket"] == "pagoseguro-datalake"
    assert subidos[0]["Key"] == "raw/extractos/qr_pagos/fecha=2026-10-01/qr_pagos_20261001_v1.txt"
    assert subidos[0]["ContentType"].startswith("text/plain")
