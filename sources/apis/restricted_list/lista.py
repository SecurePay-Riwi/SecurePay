"""Carga de la lista del proveedor y búsqueda por documento."""

import json
import re

# Solo dígitos: es como el seed guarda la lista (bitácora 3.5).
_NO_DIGITOS = re.compile(r"\D")


def normalizar(documento: str) -> str:
    """'CC 1.000.000.016' -> '1000000016'."""
    return _NO_DIGITOS.sub("", documento)


def leer_texto(config) -> str:
    """Trae el contenido del archivo del proveedor, local o de S3."""
    if config.fuente == "s3":
        # Import aquí: el modo file no necesita boto3. boto3 toma
        # AWS_ENDPOINT_URL del entorno (LocalStack en local; en AWS no
        # existe y va a S3 real con el rol de la Lambda).
        import boto3

        s3 = boto3.client("s3")
        respuesta = s3.get_object(Bucket=config.bucket, Key=config.clave_s3)
        return respuesta["Body"].read().decode("utf-8")

    if not config.archivo.exists():
        raise FileNotFoundError(
            f"No existe {config.archivo}. Corre primero el seed "
            "(uv run python -m db.seed.seed)."
        )
    return config.archivo.read_text(encoding="utf-8")


def parsear(texto: str) -> dict[str, dict]:
    """Convierte el JSON Lines en un diccionario documento -> registro."""
    lista = {}
    for numero, linea in enumerate(texto.splitlines(), start=1):
        if not linea.strip():
            continue
        try:
            registro = json.loads(linea)
            documento = normalizar(registro["documento"])
        except (json.JSONDecodeError, KeyError, TypeError) as error:
            raise ValueError(f"Línea {numero} del archivo de la lista inválida: {error}")
        lista[documento] = {
            "documento": documento,
            "tipo": registro.get("tipo"),
            "fecha_inclusion": registro.get("fecha_inclusion"),
        }
    return lista


def cargar(config) -> dict[str, dict]:
    return parsear(leer_texto(config))
