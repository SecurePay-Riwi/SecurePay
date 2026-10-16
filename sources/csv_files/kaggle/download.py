"""Descarga de los CSV desde Kaggle a una carpeta local."""

import os
from pathlib import Path

from sources.csv_files.kaggle.config import Dataset, forzar_descarga


def descargar(dataset: str, carpeta: Path, forzar: bool = False) -> None:
    # El import va dentro de la función: la librería intenta autenticarse
    # al importarse y, sin token, rompería hasta las pruebas.
    from kaggle.api.kaggle_api_extended import KaggleApi

    if not os.getenv("KAGGLE_API_TOKEN"):
        raise RuntimeError("Falta KAGGLE_API_TOKEN en el .env")

    api = KaggleApi()
    api.authenticate()
    carpeta.mkdir(parents=True, exist_ok=True)
    api.dataset_download_files(
        dataset, path=str(carpeta), unzip=True, quiet=False, force=forzar
    )


def asegurar_descargado(ds: Dataset, carpeta: Path, descargador=descargar) -> Path:
    """Devuelve la ruta local del CSV, descargándolo solo si hace falta.

    Si el archivo ya existe no se vuelve a bajar (PaySim pesa ~470 MB),
    salvo con KAGGLE_FORCE_DOWNLOAD=true. Con el archivo local presente
    tampoco se pide el token. `descargador` se puede cambiar en las pruebas.
    """
    ruta = carpeta / ds.archivo
    forzar = forzar_descarga()

    if ruta.exists() and not forzar:
        print(f"  {ds.archivo}: ya está en {carpeta}, no se descarga")
        return ruta

    print(f"  Descargando {ds.dataset} en {carpeta}...")
    descargador(ds.dataset, carpeta, forzar)
    return ruta
