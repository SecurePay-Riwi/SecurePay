"""Configuración de la descarga de los datasets de Kaggle.

Todo lo que define el contrato (datasets, archivos, columnas, número de
filas y rutas en S3) vive aquí. Si al descargar por primera vez un archivo
no coincide con estos valores, NO se corrige aquí: se avisa a Jorge.

Los datasets van a la capa cruda (raw/) del Data Lake tal como llegaron,
sin transformar. El motor no los consume; los procesa Spark después.
"""

import os
from dataclasses import dataclass
from pathlib import Path

import shared.config  # noqa: F401 (carga el .env con load_dotenv)

# Por defecto, el valor local de LocalStack (guía, sección de rutas en S3).
BUCKET_POR_DEFECTO = "pagoseguro-datalake"


@dataclass(frozen=True)
class Dataset:
    clave: str  # nombre corto, solo para los mensajes
    dataset: str  # identificador en Kaggle (dueño/nombre)
    archivo: str  # archivo CSV que se espera dentro de la descarga
    filas: int  # filas de datos, sin contar el encabezado
    columnas: tuple[str, ...]  # encabezado exacto y en orden
    clave_s3: str  # ruta del CSV en el bucket

    @property
    def clave_manifiesto(self) -> str:
        """El manifiesto va en la misma carpeta que el CSV."""
        return self.clave_s3.rsplit("/", 1)[0] + "/_manifest.json"


PAYSIM = Dataset(
    clave="paysim",
    dataset="ealaxi/paysim1",
    archivo="PS_20174392719_1491204439457_log.csv",
    filas=6_362_620,
    columnas=(
        "step",
        "type",
        "amount",
        "nameOrig",
        "oldbalanceOrg",
        "newbalanceOrig",
        "nameDest",
        "oldbalanceDest",
        "newbalanceDest",
        "isFraud",
        "isFlaggedFraud",
    ),
    clave_s3="raw/kaggle/paysim/paysim.csv",
)

CREDITCARD = Dataset(
    clave="creditcard",
    dataset="mlg-ulb/creditcardfraud",
    archivo="creditcard.csv",
    filas=284_807,
    columnas=("Time", *(f"V{i}" for i in range(1, 29)), "Amount", "Class"),
    clave_s3="raw/kaggle/creditcard/creditcard.csv",
)

# Orden en que se procesan.
DATASETS = (PAYSIM, CREDITCARD)


# Se leen al llamar (no al importar) para que un .env o una prueba que
# cambie la variable después de importar el módulo se respete.
def bucket() -> str:
    return os.getenv("DATALAKE_BUCKET", BUCKET_POR_DEFECTO)


def carpeta_descarga() -> Path:
    return Path(os.getenv("KAGGLE_DOWNLOAD_DIR") or "data/kaggle")


def forzar_descarga() -> bool:
    return os.getenv("KAGGLE_FORCE_DOWNLOAD", "").strip().lower() in {"1", "true", "yes", "si", "sí"}
