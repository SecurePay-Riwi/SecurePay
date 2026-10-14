"""Configuración del servicio de listas, con variables de entorno LISTA_*.

Se lee en una función y no al importar, para que las pruebas armen su
propia configuración sin tocar el entorno.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    # "file": lee el archivo local que deja el seed.
    # "s3": lo lee del bucket del proveedor (LocalStack en local).
    fuente: str = "file"
    archivo: Path = Path("generated/listas/lista_restrictiva.jsonl")
    bucket: str = "pagoseguro-proveedor-listas"
    clave_s3: str = "lista_restrictiva.jsonl"
    # Latencia de cada respuesta, al azar entre estos dos valores.
    latencia_min_ms: int = 50
    latencia_max_ms: int = 3000
    # Porcentaje de peticiones que responden 503, como un proveedor caído.
    falla_pct: float = 5
    # Semilla del azar de latencia y caídas. Sin semilla, cada arranque
    # se comporta distinto, como un proveedor real.
    semilla: int | None = None

    def validar(self):
        if self.fuente not in ("file", "s3"):
            raise ValueError("LISTA_SOURCE debe ser 'file' o 's3'")
        if not 0 <= self.latencia_min_ms <= self.latencia_max_ms:
            raise ValueError(
                "LISTA_LATENCIA_MIN_MS debe estar entre 0 y LISTA_LATENCIA_MAX_MS"
            )
        if not 0 <= self.falla_pct <= 100:
            raise ValueError("LISTA_FALLA_PCT debe estar entre 0 y 100")


def leer_config() -> Config:
    semilla = os.getenv("LISTA_SEMILLA")
    config = Config(
        fuente=os.getenv("LISTA_SOURCE", "file"),
        archivo=Path(os.getenv("SEED_LIST_FILE", "generated/listas/lista_restrictiva.jsonl")),
        bucket=os.getenv("PROVEEDOR_LISTAS_BUCKET", "pagoseguro-proveedor-listas"),
        clave_s3=os.getenv("PROVEEDOR_LISTAS_KEY", "lista_restrictiva.jsonl"),
        latencia_min_ms=int(os.getenv("LISTA_LATENCIA_MIN_MS", 50)),
        latencia_max_ms=int(os.getenv("LISTA_LATENCIA_MAX_MS", 3000)),
        falla_pct=float(os.getenv("LISTA_FALLA_PCT", 5)),
        semilla=int(semilla) if semilla else None,
    )
    config.validar()
    return config
