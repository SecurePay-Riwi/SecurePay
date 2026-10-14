"""Clientes de AWS (boto3) para el motor y los consumidores.

En local, AWS_ENDPOINT_URL apunta a LocalStack y boto3 manda todo ahí.
En AWS esa variable no existe y boto3 va a los servicios reales con el
rol de la tarea o de la Lambda. El código no cambia.
"""

import os

import boto3
from botocore.config import Config

import shared.config  # noqa: F401 (carga el .env con load_dotenv)

AWS_REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-2")

# Tiempos cortos y sin reintentos de boto3: quien llama decide cuándo
# reintentar. Si no, una llamada a un servicio caído puede quedarse
# colgada varios segundos dentro de boto3.
def cliente(servicio: str, read_timeout: float = 2):
    config = Config(
        connect_timeout=1,
        read_timeout=read_timeout,
        retries={"total_max_attempts": 1},
    )
    return boto3.client(servicio, region_name=AWS_REGION, config=config)
