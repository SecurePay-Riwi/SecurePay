"""ETL de los datasets históricos de Kaggle hacia la tabla transacciones.

Se ejecuta DESPUÉS del seed, desde la raíz del repositorio:

    uv run python -m db.datasets.etl --dry-run   # muestra qué haría, sin escribir
    uv run python -m db.datasets.etl             # carga las transacciones

Solo lee usuarios, dispositivos y comercios del seed y solo escribe en la
tabla transacciones. Es idempotente: correrlo otra vez no duplica nada.
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

from db.datasets.config import (
    FRAUDTEST_ARCHIVO,
    FRAUDTEST_FILAS,
    FRAUDTEST_FRAUDE_PCT,
    HASHES_ESPERADOS,
    PAYSIM_ARCHIVO,
    PAYSIM_FILAS,
    PAYSIM_FRAUDE_PCT,
    CARPETAS_CANDIDATAS,
    carpeta_raw,
)
from db.datasets.extract import muestrear_fraudtest, muestrear_paysim, sha256_archivo
from db.datasets.load import cargar_dimensiones, contar_transacciones, insertar
from db.datasets.transform import huella, transformar_fraudtest, transformar_paysim
from shared.db import get_session


def verificar_archivos(raw_dir, omitir_hash):
    """Comprueba que estén los CSV y que sean los mismos que los del equipo."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    faltan = [n for n in HASHES_ESPERADOS if not (raw_dir / n).is_file()]
    if faltan:
        carpetas = "\n  ".join(str(c) for c in CARPETAS_CANDIDATAS)
        sys.exit(
            f"Faltan estos archivos en {raw_dir}:\n  " + "\n  ".join(faltan)
            + "\nLos dos CSV deben estar juntos en una de estas carpetas:\n  "
            + carpetas
            + "\nDescárgalos como explica el README (sección \"Datasets "
            "históricos\") o indica otra carpeta con --raw-dir."
        )

    for nombre, esperado in HASHES_ESPERADOS.items():
        obtenido = sha256_archivo(raw_dir / nombre)
        estado = "OK" if obtenido == esperado else "DISTINTO"
        print(f"  {nombre}: SHA-256 {estado}")
        if obtenido != esperado and not omitir_hash:
            sys.exit(
                f"\nEl SHA-256 de {nombre} no coincide con el del equipo.\n"
                f"  esperado: {esperado}\n  obtenido: {obtenido}\n"
                "Con otra versión del archivo la muestra saldría distinta. "
                "Vuelve a descargarlo o, si lo hiciste a propósito, usa "
                "--omitir-hash (los datos ya no serán iguales a los del equipo)."
            )


def reporte_extraccion(m):
    print(f"\n[{m.dataset}] extracción")
    print(f"  filas leídas: {m.leidas:,}  |  descartadas (monto <= 0 o dato inválido): {m.descartadas:,}")
    print(f"  disponibles: {m.disponibles_fraude:,} de fraude y {m.disponibles_normales:,} normales")
    print(f"  pedidas: {m.pedidas_fraude:,} de fraude y {m.pedidas_normales:,} normales")
    print(f"  elegidas: {len(m.filas):,} ({m.fraude:,} de fraude = {100 * m.fraude / max(len(m.filas), 1):.2f} %)")
    if m.fraude < m.pedidas_fraude or len(m.filas) - m.fraude < m.pedidas_normales:
        print("  AVISO: el dataset tiene menos filas de las pedidas; se usaron todas las disponibles.")


def reporte_transformacion(lote):
    filas = lote.filas
    por_usuario = Counter(f["user_id"] for f in filas)
    fraude_por_usuario = Counter(f["user_id"] for f in filas if f["is_fraud"])
    fechas = [f["transaction_date"] for f in filas]
    print(f"\n[{lote.dataset}] transformación")
    print(f"  filas: {len(filas):,} repartidas entre {len(por_usuario):,} usuarios "
          f"(entre {min(por_usuario.values())} y {max(por_usuario.values())} por usuario)")
    print(f"  usuarios con al menos un fraude: {len(fraude_por_usuario):,} "
          f"(máximo {max(fraude_por_usuario.values(), default=0)} en uno solo)")
    print(f"  fechas: {min(fechas):%Y-%m-%d %H:%M} a {max(fechas):%Y-%m-%d %H:%M} UTC")
    print(f"  canales: {dict(sorted(Counter(f['channel'] for f in filas).items()))}")
    if lote.categoria_respetada_pct is not None:
        print(f"  comercio de la categoría equivalente: {lote.categoria_respetada_pct:.1f} % "
              "(el resto va a otra categoría porque aún no existía un comercio activo de esa)")
    print("  antes (CSV) -> después (transacciones):")
    for destino, origen in lote.ejemplos:
        print(f"    ANTES   {origen}")
        print(f"    DESPUÉS monto={destino['amount']}  fecha={destino['transaction_date']:%Y-%m-%d %H:%M:%S}  "
              f"canal={destino['channel']}  is_fraud={destino['is_fraud']}  "
              f"patron={destino['fraud_pattern']}")
        print(f"            user_id={destino['user_id']}  device_id={destino['device_id']}  "
              f"merchant_id={destino['merchant_id']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dry-run", action="store_true",
                        help="hace todo menos escribir en la base de datos")
    parser.add_argument("--raw-dir", type=Path, default=None,
                        help="carpeta con los CSV (por defecto se busca en "
                             + " y en ".join(str(c) for c in CARPETAS_CANDIDATAS) + ")")
    parser.add_argument("--omitir-hash", action="store_true",
                        help="no exige que los CSV tengan el SHA-256 del equipo")
    args = parser.parse_args()

    raw_dir = carpeta_raw(args.raw_dir)
    print(f"1/4 Verificando los CSV en {raw_dir} ...")
    verificar_archivos(raw_dir, args.omitir_hash)

    print("\n2/4 Leyendo del seed los usuarios, dispositivos y comercios...")
    session = get_session()
    try:
        dims = cargar_dimensiones(session)
        if not dims.usuarios or not dims.comercios:
            sys.exit("El seed no ha creado usuarios con dispositivo o comercios activos. "
                     "Corre primero: uv run python -m db.seed.seed")
        print(f"  {len(dims.usuarios):,} usuarios con dispositivo propio, "
              f"{len(dims.comercios):,} comercios activos")

        print("\n3/4 Extrayendo y transformando (PaySim tiene 6,3 millones de filas; tarda un poco)...")
        paysim = muestrear_paysim(raw_dir / PAYSIM_ARCHIVO, PAYSIM_FILAS, PAYSIM_FRAUDE_PCT)
        fraudtest = muestrear_fraudtest(raw_dir / FRAUDTEST_ARCHIVO, FRAUDTEST_FILAS, FRAUDTEST_FRAUDE_PCT)
        reporte_extraccion(paysim)
        reporte_extraccion(fraudtest)

        lotes = [transformar_paysim(paysim.filas, dims), transformar_fraudtest(fraudtest.filas, dims)]
        for lote in lotes:
            reporte_transformacion(lote)

        filas = [f for lote in lotes for f in lote.filas]
        print(f"\nHuella SHA-256 del lote ({len(filas):,} filas): {huella(filas)}")
        print("Si tus compañeros usan los mismos CSV, el mismo seed y la misma semilla, "
              "deben ver esta misma huella.")

        if args.dry_run:
            print("\n4/4 --dry-run: no se escribió nada en la base de datos.")
            return

        print("\n4/4 Cargando en la tabla transacciones...")
        antes = contar_transacciones(session)
        insertar(session, filas)
        despues = contar_transacciones(session)
        nuevas = despues - antes
        print(f"  insertadas: {nuevas:,}  |  ya existían: {len(filas) - nuevas:,}")
        print(f"  transacciones en la tabla: {antes:,} -> {despues:,}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
