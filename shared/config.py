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

# Decimales de cada moneda. El yen no lleva decimales.
MONEDA_DECIMALES = {"COP": 2, "USD": 2, "EUR": 2, "JPY": 0}
