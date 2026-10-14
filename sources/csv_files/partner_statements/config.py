"""Configuración del generador de extractos de los socios.

Todo se ajusta con variables de entorno EXT_*, sin tocar código. La
semilla es la misma del resto del proyecto (SEED), así dos corridas sobre
la misma salida del generador dan los mismos archivos.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

SEED = int(os.getenv("SEED", 42))

# De dónde lee: la carpeta del generador de transacciones (todas sus
# instancias, generated/instance-*/).
INPUT_DIR = Path(os.getenv("EXT_INPUT_DIR", os.getenv("GEN_OUTPUT_DIR", "generated")))

# "file": deja los extractos solo en EXT_OUTPUT_DIR.
# "s3": además los sube a la capa raw del Data Lake (LocalStack en local).
OUTPUT = os.getenv("EXT_OUTPUT", "file")
OUTPUT_DIR = Path(os.getenv("EXT_OUTPUT_DIR", "generated/extractos"))
BUCKET = os.getenv("DATALAKE_BUCKET", "pagoseguro-datalake")
PREFIJO_S3 = "raw/extractos"

# --- Defectos que pide el enunciado, en porcentaje ---------------------------

# Por transacción: el socio no la reporta (faltante en el socio).
MISSING_PERCENTAGE = float(os.getenv("EXT_MISSING_PCT", 2))
# Por transacción: el socio reporta una operación que PagoSeguro no tiene
# (faltante en PagoSeguro). Se calcula sobre las transacciones del archivo.
EXTRA_PERCENTAGE = float(os.getenv("EXT_EXTRA_PCT", 1))
# Por transacción: el socio redondea el monto a la unidad.
ROUNDING_PERCENTAGE = float(os.getenv("EXT_ROUNDING_PCT", 3))
# Por archivo: el socio reenvía el archivo del día (v2) corrigiendo los
# faltantes y los redondeos del primero. Solo se aplica a archivos que
# tengan algo que corregir.
RESEND_PERCENTAGE = float(os.getenv("EXT_RESEND_PCT", 10))
# Por archivo: el registro de control declara otra cantidad o total.
BAD_CONTROL_PERCENTAGE = float(os.getenv("EXT_BAD_CONTROL_PCT", 10))


def validar():
    """Falla al arrancar si algún valor no tiene sentido."""
    if OUTPUT not in ("file", "s3"):
        raise ValueError("EXT_OUTPUT debe ser 'file' o 's3'")

    porcentajes = {
        "EXT_MISSING_PCT": MISSING_PERCENTAGE,
        "EXT_EXTRA_PCT": EXTRA_PERCENTAGE,
        "EXT_ROUNDING_PCT": ROUNDING_PERCENTAGE,
        "EXT_RESEND_PCT": RESEND_PERCENTAGE,
        "EXT_BAD_CONTROL_PCT": BAD_CONTROL_PERCENTAGE,
    }
    for nombre, valor in porcentajes.items():
        if not 0 <= valor <= 100:
            raise ValueError(f"{nombre} debe estar entre 0 y 100")
