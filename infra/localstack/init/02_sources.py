"""Crea en LocalStack los recursos de las fuentes de datos simuladas.

LocalStack ejecuta los archivos de ready.d en orden alfabético, así que
este corre después de 01_messaging.py. Es la versión local de lo que
después hará Terraform en AWS.

- Bucket `pagoseguro-proveedor-listas`: hace de base del proveedor de
  listas restrictivas. El seed sube aquí la lista y el servicio simulado
  la lee al arrancar (bitácora 3.10). Va aparte del Data Lake porque son
  datos de un tercero, no nuestros: así el servicio no necesita permiso
  sobre el Data Lake.
"""

import boto3

REGION = "us-east-2"
ENDPOINT = "http://localhost:4566"

BUCKET_PROVEEDOR_LISTAS = "pagoseguro-proveedor-listas"

s3 = boto3.client(
    "s3",
    region_name=REGION,
    endpoint_url=ENDPOINT,
    aws_access_key_id="test",
    aws_secret_access_key="test",
)

s3.create_bucket(
    Bucket=BUCKET_PROVEEDOR_LISTAS,
    CreateBucketConfiguration={"LocationConstraint": REGION},
)

print(f"Fuentes listas: bucket {BUCKET_PROVEEDOR_LISTAS}")
