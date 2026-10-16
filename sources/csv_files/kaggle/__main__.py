"""Punto de entrada de la carga de los datasets de Kaggle.

    uv run python -m sources.csv_files.kaggle

Para cada dataset: descarga (si no está en KAGGLE_DOWNLOAD_DIR), valida
encabezado y número de filas, y lo sube a raw/kaggle/ del Data Lake con su
manifiesto. Correrlo otra vez no duplica nada: con el mismo SHA-256 dice
"ya cargado". Si algún dataset falla, los demás se procesan igual y el
comando termina con código 1.
"""

import sys

from shared.aws import cliente
from sources.csv_files.kaggle import config
from sources.csv_files.kaggle.download import asegurar_descargado
from sources.csv_files.kaggle.upload import subir


def main() -> int:
    carpeta = config.carpeta_descarga()
    bucket = config.bucket()
    # Archivos grandes: más tiempo de lectura que el de por defecto.
    s3 = cliente("s3", read_timeout=60)

    resultados, errores = [], []
    for ds in config.DATASETS:
        print(f"{ds.dataset}")
        try:
            ruta = asegurar_descargado(ds, carpeta)
            print("  Validando y subiendo (archivo grande, puede tardar)...")
            resultados.append(subir(ds, ruta, s3, bucket))
        except Exception as e:  # se informa y se sigue con el otro dataset
            errores.append((ds.clave, e))
            print(f"  ERROR: {e}", file=sys.stderr)

    print("\nResumen")
    for r in resultados:
        print(f"  {r.dataset:<11} {r.filas:>9} filas  {r.bytes / 1024 / 1024:>8.1f} MB  {r.estado}")
    for clave, e in errores:
        print(f"  {clave:<11} FALLÓ: {e}")

    return 1 if errores else 0


if __name__ == "__main__":
    sys.exit(main())
