"""Valida los CSV de Kaggle y los sube a la capa raw del Data Lake.

Orden de seguridad: primero se valida todo, después se sube el CSV y solo
cuando terminó bien se escribe el manifiesto. El manifiesto es la señal de
"carga completa": si la subida falla, no se publica ninguno nuevo. Como S3
reemplaza el objeto solo cuando la subida por partes termina, el manifiesto
anterior (si lo había) sigue describiendo el CSV anterior.
"""

import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from botocore.exceptions import ClientError

from sources.csv_files.kaggle.config import Dataset

SUBIDO = "subido"
YA_CARGADO = "ya cargado"

_BLOQUE = 1024 * 1024


class ErrorValidacion(Exception):
    """El archivo no cumple el contrato del dataset: no se sube nada."""


@dataclass(frozen=True)
class Resultado:
    dataset: str
    filas: int
    bytes: int
    estado: str  # SUBIDO o YA_CARGADO


def inspeccionar(ruta: Path) -> tuple[list[str], int, str]:
    """Devuelve (columnas, filas, sha256) leyendo el archivo por bloques y
    por líneas, nunca entero en memoria."""
    sha = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(_BLOQUE), b""):
            sha.update(bloque)

    with open(ruta, newline="", encoding="utf-8") as f:
        lector = csv.reader(f)
        columnas = next(lector, [])
        filas = sum(1 for _ in lector)

    return columnas, filas, sha.hexdigest()


def validar(ds: Dataset, ruta: Path) -> tuple[list[str], int, str]:
    """Comprueba existencia, encabezado exacto y número de filas.

    Devuelve (columnas, filas, sha256) o lanza ErrorValidacion.
    """
    if not ruta.is_file():
        raise ErrorValidacion(f"{ds.clave}: no existe el archivo {ruta}")

    columnas, filas, sha = inspeccionar(ruta)

    esperadas = list(ds.columnas)
    if columnas != esperadas:
        faltan = [c for c in esperadas if c not in columnas]
        sobran = [c for c in columnas if c not in esperadas]
        detalle = "mismas columnas pero en otro orden" if not faltan and not sobran else (
            f"faltan {faltan}, sobran {sobran}"
        )
        raise ErrorValidacion(
            f"{ds.clave}: el encabezado de {ruta.name} no coincide con el contrato ({detalle})"
        )

    if filas != ds.filas:
        raise ErrorValidacion(
            f"{ds.clave}: {ruta.name} tiene {filas} filas y se esperaban {ds.filas}"
        )

    return columnas, filas, sha


def construir_manifiesto(
    ds: Dataset, columnas: list[str], filas: int, sha256: str, tamano: int
) -> dict:
    return {
        "dataset": ds.dataset,
        "archivo_original": ds.archivo,
        "filas": filas,
        "columnas": columnas,
        "sha256": sha256,
        "bytes": tamano,
        "cargado_en": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _no_existe(error: ClientError) -> bool:
    return error.response.get("Error", {}).get("Code") in {"NoSuchKey", "404", "NotFound"}


def leer_manifiesto_remoto(s3, bucket: str, clave: str) -> dict | None:
    """El manifiesto que hay en S3, o None si no existe. Cualquier otro
    error (permisos, red) sube: no se confunde con "no hay carga"."""
    try:
        cuerpo = s3.get_object(Bucket=bucket, Key=clave)["Body"].read()
    except ClientError as e:
        if _no_existe(e):
            return None
        raise
    return json.loads(cuerpo)


def _csv_remoto_coincide(s3, bucket: str, clave: str, tamano: int) -> bool:
    """El CSV está en S3 y pesa lo que dice el manifiesto."""
    try:
        return s3.head_object(Bucket=bucket, Key=clave)["ContentLength"] == tamano
    except ClientError as e:
        if _no_existe(e):
            return False
        raise


def subir(ds: Dataset, ruta: Path, s3, bucket: str) -> Resultado:
    """Valida y sube un dataset. Idempotente: con el mismo SHA-256 ya
    cargado no sube nada. Ante cualquier fallo lanza excepción."""
    columnas, filas, sha = validar(ds, ruta)
    tamano = ruta.stat().st_size

    remoto = leer_manifiesto_remoto(s3, bucket, ds.clave_manifiesto)
    if (
        remoto
        and remoto.get("sha256") == sha
        and _csv_remoto_coincide(s3, bucket, ds.clave_s3, tamano)
    ):
        return Resultado(ds.clave, filas, tamano, YA_CARGADO)

    manifiesto = construir_manifiesto(ds, columnas, filas, sha, tamano)

    # 1. El CSV. Si falla, la excepción sale y no se escribe el manifiesto.
    s3.upload_file(str(ruta), bucket, ds.clave_s3)

    # 2. El manifiesto, solo cuando el CSV ya está completo.
    s3.put_object(
        Bucket=bucket,
        Key=ds.clave_manifiesto,
        Body=json.dumps(manifiesto, indent=2).encode("utf-8"),
        ContentType="application/json",
    )
    return Resultado(ds.clave, filas, tamano, SUBIDO)
