import os
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://pagoseguro:pagoseguro@localhost:5432/pagoseguro"
)

# Fecha fija desde la que se calculan las fechas del seed y del generador.
# Así dos corridas dan los mismos datos sin importar el día.
FECHA_REFERENCIA = datetime(2026, 10, 1, tzinfo=timezone.utc)

# Canales por los que llega cada tipo de operación. Los usan el generador
# (core simulado) y el ETL de Kaggle, que no deben importarse entre sí.
CANALES = {
    "P2P": ["APP", "WEB"],
    "QR": ["APP"],
    "RECARGA": ["APP", "WEB", "CORRESPONSAL"],
    "RETIRO": ["CORRESPONSAL", "CAJERO"],
}

# Decimales de cada moneda. El yen no lleva decimales.
MONEDA_DECIMALES = {"COP": 2, "USD": 2, "EUR": 2, "JPY": 0}
