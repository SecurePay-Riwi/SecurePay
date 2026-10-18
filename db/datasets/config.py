"""Configuración del ETL de los datasets históricos de Kaggle.

Toma una muestra fija de PaySim y de fraudTest y la carga en la tabla
transacciones, repartida entre los usuarios, dispositivos y comercios que
ya creó el seed. Con la misma semilla, los mismos CSV y el mismo seed,
todos obtienen exactamente los mismos datos. Todo se ajusta aquí o con
variables de entorno, sin tocar código.
"""

import os
import random
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

# Misma semilla y misma fecha fija que el seed, para que todo el azar de
# este ETL cuelgue de los mismos valores.
from db.seed.config import SEED
from shared.config import FECHA_REFERENCIA

load_dotenv()

# --- Archivos --------------------------------------------------------------

PAYSIM_ARCHIVO = "PS_20174392719_1491204439457_log.csv"
FRAUDTEST_ARCHIVO = "fraudTest.csv"

ARCHIVOS = (PAYSIM_ARCHIVO, FRAUDTEST_ARCHIVO)

# Carpetas donde se buscan los CSV, en este orden. La segunda es la misma que
# usa la carga al Data Lake (sources.csv_files.kaggle), para no descargar
# 600 MB dos veces: basta con que los dos CSV estén juntos en una de las dos.
CARPETAS_CANDIDATAS = (
    Path(__file__).parent / "raw",
    Path(os.getenv("KAGGLE_DOWNLOAD_DIR", "data/kaggle")),
)


def carpeta_raw(explicita=None, candidatas=None):
    """Carpeta de la que se leen los CSV.

    Manda lo que se pida (--raw-dir, y después la variable HIST_RAW_DIR).
    Si no se pide nada, se usa la primera carpeta candidata que tenga los dos
    archivos; si ninguna los tiene, la primera, para que el error la nombre.
    """
    if explicita is not None:
        return Path(explicita)
    if os.getenv("HIST_RAW_DIR"):
        return Path(os.environ["HIST_RAW_DIR"])
    candidatas = candidatas or CARPETAS_CANDIDATAS
    for carpeta in candidatas:
        if all((carpeta / nombre).is_file() for nombre in ARCHIVOS):
            return carpeta
    return candidatas[0]


# SHA-256 de los CSV con los que se diseñó el ETL. Si el de un compañero es
# distinto, tiene otra versión del archivo y la muestra saldría distinta.
HASHES_ESPERADOS = {
    PAYSIM_ARCHIVO: "16910f90577b0d981bf8ff289714510bb89bc71bff7d3f220f024e287e4eea6b",
    FRAUDTEST_ARCHIVO: "12d553ab19440c752d2531ee1af44bb64f12cc3d3839f1649f19e81c230545f0",
}

# --- Tamaño de la muestra --------------------------------------------------
# Total de transacciones que se toman de cada dataset y qué porcentaje de
# ellas son fraude. Se eligen a propósito: con una muestra al azar sin
# más, el fraude sería de 0,13 % (PaySim) y 0,39 % (fraudTest) y el motor
# antifraude casi no tendría casos con qué validarse.
PAYSIM_FILAS = int(os.getenv("HIST_PAYSIM_FILAS", 50_000))
PAYSIM_FRAUDE_PCT = float(os.getenv("HIST_PAYSIM_FRAUDE_PCT", 3))
FRAUDTEST_FILAS = int(os.getenv("HIST_FRAUDTEST_FILAS", 20_000))
FRAUDTEST_FRAUDE_PCT = float(os.getenv("HIST_FRAUDTEST_FRAUDE_PCT", 3))

# Cuántas filas se mandan a PostgreSQL por llamada.
TAMANO_LOTE = int(os.getenv("HIST_TAMANO_LOTE", 5_000))

# --- Correspondencias con lo que genera el seed ----------------------------

# Tipo de PaySim -> tipo de operación del generador (P2P, QR, RECARGA,
# RETIRO). Define el canal. DEBIT en PaySim es una salida de dinero hacia
# un banco, lo más parecido a un retiro.
TIPO_PAYSIM = {
    "TRANSFER": "P2P",
    "PAYMENT": "QR",
    "CASH_IN": "RECARGA",
    "CASH_OUT": "RETIRO",
    "DEBIT": "RETIRO",
}

# Categoría de fraudTest -> categoría de comercio del seed. fraudTest trae
# 14; el seed solo 5. Cambiar una línea basta para reagruparlas.
CATEGORIA_FRAUDTEST = {
    "food_dining": "alimentos",
    "grocery_net": "alimentos",
    "grocery_pos": "alimentos",
    "health_fitness": "salud",
    "personal_care": "salud",
    "shopping_net": "retail",
    "shopping_pos": "retail",
    "home": "retail",
    "kids_pets": "retail",
    "misc_pos": "retail",
    "gas_transport": "servicios",
    "travel": "servicios",
    "entertainment": "servicios",
    "misc_net": "tecnologia",
}

# --- Fechas ----------------------------------------------------------------
# Todo queda antes de la fecha de referencia del seed, como si fuera el
# historial previo del sistema. Las fechas se manejan en UTC sin zona
# horaria, igual que las columnas del seed.
_REFERENCIA = FECHA_REFERENCIA.replace(tzinfo=None)

# PaySim no trae fechas: solo "step", la hora de la simulación (1 a 743,
# unos 31 días). La hora 1 cae 31 días antes de la referencia.
PAYSIM_INICIO = _REFERENCIA - timedelta(days=31)

# fraudTest va de junio a diciembre de 2020, antes de que existiera
# cualquier usuario del seed (se registran en los últimos 3 años). Se corre
# todo el rango, sin cambiar la separación entre transacciones, para que
# su última fecha quede justo antes de la referencia.
FRAUDTEST_FIN_ORIGINAL = datetime(2021, 1, 1)
FRAUDTEST_DESPLAZAMIENTO = _REFERENCIA - FRAUDTEST_FIN_ORIGINAL

# --- Azar ------------------------------------------------------------------

PREFIJO_PATRON = "kaggle"


def nuevo_rng(dataset, proposito):
    """Generador de azar propio de cada dataset y de cada propósito.

    Sale de la semilla del seed (SEED, 42 por defecto). Así cambiar el
    tamaño de la muestra de un dataset no mueve los datos del otro, y
    random.Random con un texto da la misma secuencia en cualquier sistema
    operativo.
    """
    return random.Random(f"securepay:{SEED}:hist:{dataset}:{proposito}")
