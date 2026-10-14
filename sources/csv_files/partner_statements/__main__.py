"""Punto de entrada del generador de extractos de los socios.

    uv run python -m sources.csv_files.partner_statements

Lee la salida del generador de transacciones (corre primero
`uv run python -m generators`), arma un archivo por socio y por día con
sus defectos, y los deja en generated/extractos/ y, con EXT_OUTPUT=s3,
también en la capa raw del Data Lake.
"""

from collections import Counter

from sources.csv_files.partner_statements import config
from sources.csv_files.partner_statements.output import (
    SalidaLocal,
    SalidaS3,
    ruta_relativa,
)
from sources.csv_files.partner_statements.reader import leer
from sources.csv_files.partner_statements.statements import Generador, Porcentajes


def main():
    config.validar()
    print(f"Leyendo la salida del generador en {config.INPUT_DIR}...")
    operaciones = leer(config.INPUT_DIR)
    print(f"  {len(operaciones)} operaciones pasan por algún socio")

    porcentajes = Porcentajes(
        faltantes=config.MISSING_PERCENTAGE,
        extras=config.EXTRA_PERCENTAGE,
        redondeo=config.ROUNDING_PERCENTAGE,
        reenvio=config.RESEND_PERCENTAGE,
        control=config.BAD_CONTROL_PERCENTAGE,
    )
    generador = Generador(config.SEED, porcentajes)
    archivos = generador.construir(operaciones)

    local = SalidaLocal(config.OUTPUT_DIR)
    s3 = SalidaS3(config.BUCKET, config.PREFIJO_S3) if config.OUTPUT == "s3" else None

    filas = []
    for socio, extracto in archivos:
        relativa = ruta_relativa(socio, extracto)
        contenido = socio.escribir(extracto)
        local.guardar(relativa, contenido)
        if s3:
            s3.guardar(relativa, contenido)

        real = socio.control_real(extracto.registros)
        declarado = extracto.control or real
        filas.append({
            "partner": socio.nombre,
            "day": extracto.dia.isoformat(),
            "version": extracto.version,
            "file": relativa,
            "records": len(extracto.registros),
            "control_declared": {"count": declarado[0], "total": str(declarado[1])},
            "control_actual": {"count": real[0], "total": str(real[1])},
            "control_matches": declarado == real,
        })

    resumen = {
        "parameters": {
            "seed": config.SEED,
            "input_dir": str(config.INPUT_DIR),
            "missing_pct": config.MISSING_PERCENTAGE,
            "extra_pct": config.EXTRA_PERCENTAGE,
            "rounding_pct": config.ROUNDING_PERCENTAGE,
            "resend_pct": config.RESEND_PERCENTAGE,
            "bad_control_pct": config.BAD_CONTROL_PERCENTAGE,
        },
        "operations_read": len(operaciones),
        "files_by_partner": dict(Counter(f["partner"] for f in filas)),
        "defects_by_type": dict(Counter(d["defect"] for d in generador.defectos)),
        "expected_differences_by_type": dict(Counter(d["type"] for d in generador.diferencias)),
        "files": filas,
        "defects": generador.defectos,
        "expected_differences": generador.diferencias,
    }
    ruta = local.reporte(resumen)

    print(f"Listo: {len(filas)} archivos en {config.OUTPUT_DIR}"
          + (f" y en s3://{config.BUCKET}/{config.PREFIJO_S3}/" if s3 else ""))
    print(f"  Por socio: {resumen['files_by_partner']}")
    print(f"  Defectos: {resumen['defects_by_type']}")
    print(f"  Diferencias esperadas: {resumen['expected_differences_by_type']}")
    print(f"  Reporte: {ruta}")


if __name__ == "__main__":
    main()
