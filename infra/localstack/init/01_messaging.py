"""Crea en LocalStack la mensajería y el bucket del Data Lake.

LocalStack ejecuta este archivo al arrancar (carpeta ready.d). Es la
versión local de lo que después hará Terraform en AWS, con la misma
configuración de la bitácora (sección 3, Mensajería):

- Tema SNS `decisiones`, donde el motor publica cada decisión.
- Colas SQS `casos`, `historial` y `analitica`, suscritas al tema sin
  filtros, cada una con su cola de errores (`<cola>-dlq`).
- Un mensaje que falla 5 veces pasa a la cola de errores, que lo guarda
  14 días (el máximo de SQS).
- Bucket `pagoseguro-datalake`, donde analítica deja la capa `raw/`.
- SNS topic `business-alerts` (Sprint 4): the alerts task publishes the
  supervisor escalations and the compliance summary there. No queues: in
  local the e-mails are only seen in LocalStack's logs.

Va en Python y no en bash porque LocalStack ejecuta los .sh directo:
un .sh guardado desde Windows (sin permiso de ejecución o con fin de
línea CRLF) falla al arrancar.
"""

import json

import boto3

REGION = "us-east-2"
ENDPOINT = "http://localhost:4566"

TEMA = "decisiones"
COLAS = ["casos", "historial", "analitica"]
BUCKET = "pagoseguro-datalake"
BUSINESS_ALERTS_TOPIC = "business-alerts"

REINTENTOS_ANTES_DE_DLQ = 5
RETENCION_DLQ_S = 14 * 24 * 3600
# Cuánto tiempo queda invisible un mensaje leído antes de reintentarse si el
# consumidor no lo borra. En AWS será 6 veces el timeout de la Lambda.
VISIBILIDAD_S = 30


def cliente(servicio):
    return boto3.client(
        servicio,
        region_name=REGION,
        endpoint_url=ENDPOINT,
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )


sns = cliente("sns")
sqs = cliente("sqs")
s3 = cliente("s3")

tema_arn = sns.create_topic(Name=TEMA)["TopicArn"]

for nombre in COLAS:
    dlq_url = sqs.create_queue(
        QueueName=f"{nombre}-dlq",
        Attributes={"MessageRetentionPeriod": str(RETENCION_DLQ_S)},
    )["QueueUrl"]
    dlq_arn = sqs.get_queue_attributes(
        QueueUrl=dlq_url, AttributeNames=["QueueArn"]
    )["Attributes"]["QueueArn"]

    cola_url = sqs.create_queue(
        QueueName=nombre,
        Attributes={
            "VisibilityTimeout": str(VISIBILIDAD_S),
            "RedrivePolicy": json.dumps(
                {
                    "deadLetterTargetArn": dlq_arn,
                    "maxReceiveCount": str(REINTENTOS_ANTES_DE_DLQ),
                }
            ),
        },
    )["QueueUrl"]
    cola_arn = sqs.get_queue_attributes(
        QueueUrl=cola_url, AttributeNames=["QueueArn"]
    )["Attributes"]["QueueArn"]

    # En AWS, Terraform además agrega a cada cola una política que deja a
    # este tema escribir en ella. LocalStack no revisa permisos.
    #
    # RawMessageDelivery: la cola recibe el evento tal cual, sin el sobre
    # JSON que SNS agrega por defecto. Así el consumidor lee el mismo JSON
    # que publicó el motor.
    sns.subscribe(
        TopicArn=tema_arn,
        Protocol="sqs",
        Endpoint=cola_arn,
        Attributes={"RawMessageDelivery": "true"},
    )

s3.create_bucket(
    Bucket=BUCKET,
    CreateBucketConfiguration={"LocationConstraint": REGION},
)

sns.create_topic(Name=BUSINESS_ALERTS_TOPIC)

print(
    f"Mensajería lista: tema {TEMA}, colas {COLAS}, bucket {BUCKET} "
    f"y tema {BUSINESS_ALERTS_TOPIC}"
)
