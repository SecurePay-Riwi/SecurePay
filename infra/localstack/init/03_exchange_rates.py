"""Crea en LocalStack la tabla de tasas de cambio.

Corre después de 02_sources.py (LocalStack ejecuta ready.d en orden
alfabético). Es la versión local de lo que después hará Terraform en AWS.

Tabla `pagoseguro-exchange-rates`: una fila por día publicado por
Frankfurter. La escribe securepay-apis (la Lambda diaria, o el comando
local con RATES_OUTPUT=dynamodb) y la lee el motor, que convierte cada
transacción a USD con la tasa de su propia fecha.

- base (partición): siempre "USD".
- rate_date (ordenamiento): "AAAA-MM-DD". Con esta clave, una sola
  consulta trae el último día o todos ya ordenados.
- expires_at: TTL. En AWS, DynamoDB borra la fila 30 días después de
  escrita. LocalStack solo borra vencidos con DYNAMODB_REMOVE_EXPIRED_ITEMS=1,
  que no se activa: en local las tasas de octubre se quedan.
"""

import boto3

REGION = "us-east-2"
ENDPOINT = "http://localhost:4566"

TABLA_TASAS = "pagoseguro-exchange-rates"

dynamodb = boto3.client(
    "dynamodb",
    region_name=REGION,
    endpoint_url=ENDPOINT,
    aws_access_key_id="test",
    aws_secret_access_key="test",
)

dynamodb.create_table(
    TableName=TABLA_TASAS,
    KeySchema=[
        {"AttributeName": "base", "KeyType": "HASH"},
        {"AttributeName": "rate_date", "KeyType": "RANGE"},
    ],
    AttributeDefinitions=[
        {"AttributeName": "base", "AttributeType": "S"},
        {"AttributeName": "rate_date", "AttributeType": "S"},
    ],
    # Bajo demanda: unas pocas escrituras y lecturas al día.
    BillingMode="PAY_PER_REQUEST",
)
dynamodb.get_waiter("table_exists").wait(TableName=TABLA_TASAS)
dynamodb.update_time_to_live(
    TableName=TABLA_TASAS,
    TimeToLiveSpecification={"Enabled": True, "AttributeName": "expires_at"},
)

print(f"Tasas lista: tabla {TABLA_TASAS}")
