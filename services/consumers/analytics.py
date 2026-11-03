"""Consumidor de analítica: deja las decisiones en la capa raw del Data Lake.

Cada lote se escribe como un archivo JSON Lines (un evento por línea) en
s3://<bucket>/raw/decisiones/fecha=AAAA-MM-DD/, particionado por el día en
que llegó. De ahí lo lee el ETL de Spark para la capa curated.

Si SQS entrega un mensaje dos veces, la línea queda repetida en raw: la
capa raw guarda lo que llegó sin tocarlo y la curated elimina duplicados
por id de transacción.

In AWS the queue mapping sends batches of up to 1,000 decisions (or what
arrives in 60 seconds), so each S3 object is big: batches of 10 would be
~13 million PUTs a month. Firehose was planned for this, but it is not on
AWS's free plan (modules/lambdas, analytics_batch_size). Locally the runner
keeps batches of 10.
"""

import json
import logging
import os
from datetime import UTC, datetime
from uuid import uuid4

from services.consumers.batch import leer_lote, respuesta
from shared.aws import cliente

log = logging.getLogger(__name__)

BUCKET = os.getenv("DATALAKE_BUCKET", "pagoseguro-datalake")
PREFIJO = "raw/decisiones"

_s3 = None


def _cliente_s3():
    global _s3
    if _s3 is None:
        _s3 = cliente("s3")
    return _s3


def handler(event, context=None):
    validos, fallidos = leer_lote(event)

    if validos:
        try:
            clave = escribir_en_raw([evento for _, evento in validos])
            log.info("Analítica: %d eventos en s3://%s/%s", len(validos), BUCKET, clave)
        except Exception:
            # Sin archivo no hay nada guardado: todo el lote se reintenta.
            log.exception("Analítica: no se pudo escribir en S3")
            fallidos += [mensaje_id for mensaje_id, _ in validos]

    return respuesta(fallidos)


def escribir_en_raw(eventos: list[dict]) -> str:
    ahora = datetime.now(UTC)
    clave = f"{PREFIJO}/fecha={ahora:%Y-%m-%d}/{ahora:%H%M%S}-{uuid4().hex}.jsonl"
    cuerpo = "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in eventos)

    _cliente_s3().put_object(
        Bucket=BUCKET,
        Key=clave,
        Body=cuerpo.encode("utf-8"),
        ContentType="application/x-ndjson",
    )
    return clave
