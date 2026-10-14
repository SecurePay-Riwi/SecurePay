"""Exporta la lista restrictiva al archivo que hace de base del proveedor.

El servicio simulado de listas restrictivas (sources/apis/restricted_list/)
lee este archivo una vez al arrancar (bitácora 3.10). No lee PostgreSQL:
así su Lambda queda fuera de la VPC y el servicio se puede mover a otro
repo sin depender del seed.

Formato JSON Lines, una persona por línea, ordenado por documento:

    {"documento": "1000000016", "tipo": "sanciones", "fecha_inclusion": "2023-04-11"}

Con SEED_LIST_OUTPUT=s3 también se sube al bucket del proveedor
(LocalStack en local).
"""

import json
import os
from pathlib import Path

from shared.models import ListaRestrictiva

OUTPUT = os.getenv("SEED_LIST_OUTPUT", "file")
ARCHIVO = Path(os.getenv("SEED_LIST_FILE", "generated/listas/lista_restrictiva.jsonl"))
BUCKET = os.getenv("PROVEEDOR_LISTAS_BUCKET", "pagoseguro-proveedor-listas")
CLAVE_S3 = os.getenv("PROVEEDOR_LISTAS_KEY", "lista_restrictiva.jsonl")


def a_jsonl(filas) -> str:
    """Convierte las filas de la lista en el contenido del archivo."""
    lineas = [
        json.dumps(
            {
                "documento": f.documento,
                "tipo": f.tipo,
                "fecha_inclusion": f.fecha_inclusion.isoformat(),
            },
            ensure_ascii=False,
        )
        for f in sorted(filas, key=lambda f: f.documento)
    ]
    return "".join(linea + "\n" for linea in lineas)


def guardar_local(contenido: str, ruta: Path = ARCHIVO) -> Path:
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    # newline="\n": el mismo archivo byte a byte en Windows y en Linux.
    ruta.write_text(contenido, encoding="utf-8", newline="\n")
    return ruta


def subir_s3(contenido: str, bucket: str = BUCKET, clave: str = CLAVE_S3):
    # Import aquí: el modo file no necesita boto3 ni LocalStack.
    from shared.aws import cliente

    cliente("s3", read_timeout=10).put_object(
        Bucket=bucket,
        Key=clave,
        Body=contenido.encode("utf-8"),
        ContentType="application/x-ndjson; charset=utf-8",
    )


def exportar_lista(session):
    """Lee la lista de PostgreSQL y la escribe en el archivo (y en S3).

    Lee de la tabla y no de lo que acaba de generar el seed: con
    SEED_RESET=false la tabla puede traer filas de una corrida anterior, y
    el proveedor debe tener exactamente lo que tiene la base.
    """
    if OUTPUT not in ("file", "s3"):
        raise ValueError("SEED_LIST_OUTPUT debe ser 'file' o 's3'")

    filas = session.query(ListaRestrictiva).all()
    contenido = a_jsonl(filas)

    ruta = guardar_local(contenido)
    print(f"  Lista del proveedor: {len(filas)} personas en {ruta}")

    if OUTPUT == "s3":
        subir_s3(contenido)
        print(f"  Subida a s3://{BUCKET}/{CLAVE_S3}")
