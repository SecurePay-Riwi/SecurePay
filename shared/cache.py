import os

import valkey

import shared.config  # noqa: F401 (carga el .env con load_dotenv)

VALKEY_URL = os.getenv("VALKEY_URL", "redis://localhost:6379/0")

# Un solo cliente por proceso: maneja su propio pool de conexiones.
# decode_responses=True devuelve str en vez de bytes.
cliente = valkey.Valkey.from_url(VALKEY_URL, decode_responses=True)


def get_cache():
    return cliente
