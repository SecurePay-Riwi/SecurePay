"""De punta a punta contra LocalStack: motor → SNS → 3 colas → analítica → S3.

Se omite si LocalStack no está levantado (docker compose up -d).
"""

import json
from uuid import uuid4

import pytest

from services.consumers import analytics
from services.consumers.runner import atender_lote
from services.decision_engine.publisher import TOPIC_ARN, Publicador
from shared.aws import cliente
from shared.events import evento_decision

COLAS = ["casos", "historial", "analitica"]


@pytest.fixture(scope="module")
def aws():
    try:
        sns, sqs, s3 = cliente("sns"), cliente("sqs"), cliente("s3")
        sqs.get_queue_url(QueueName="analitica")
    except Exception:
        pytest.skip("LocalStack no está disponible (docker compose up -d)")

    urls = {c: sqs.get_queue_url(QueueName=c)["QueueUrl"] for c in COLAS}
    return sns, sqs, s3, urls


@pytest.fixture(autouse=True)
def colas_vacias(aws):
    """Lo que dejó otra prueba o corrida no debe contar aquí."""
    _, sqs, _, urls = aws
    for url in urls.values():
        _borrar(sqs, url, _leer_todo(sqs, url))
    yield
    for url in urls.values():
        _borrar(sqs, url, _leer_todo(sqs, url))


def _evento(tx_id, decision="APPROVE"):
    return evento_decision(
        {"id": tx_id},
        {
            "transaction_id": tx_id,
            "decision": decision,
            "decision_reason": "Prueba",
            "processed_at": "2026-10-13T20:00:00+00:00",
        },
    )


def _leer_todo(sqs, url):
    mensajes = []
    while True:
        lote = sqs.receive_message(
            QueueUrl=url, MaxNumberOfMessages=10, WaitTimeSeconds=1
        ).get("Messages", [])
        if not lote:
            return mensajes
        mensajes += lote


def _borrar(sqs, url, mensajes):
    for i in range(0, len(mensajes), 10):
        sqs.delete_message_batch(
            QueueUrl=url,
            Entries=[
                {"Id": str(j), "ReceiptHandle": m["ReceiptHandle"]}
                for j, m in enumerate(mensajes[i : i + 10])
            ],
        )


def test_each_decision_reaches_the_three_queues(aws):
    _, sqs, _, urls = aws
    ids = [str(uuid4()) for _ in range(12)]

    pub = Publicador(topic_arn=TOPIC_ARN)
    for tx_id in ids:
        pub.publicar(_evento(tx_id))
    pub.detener()

    assert pub.estado() == {"pendientes": 0, "publicados": 12, "fallidos": 0}

    for cola, url in urls.items():
        mensajes = _leer_todo(sqs, url)
        # RawMessageDelivery: el cuerpo es el evento tal cual, sin sobre de SNS.
        recibidos = {json.loads(m["Body"])["transaction"]["id"] for m in mensajes}
        assert recibidos == set(ids), cola


def test_analytics_consumer_writes_to_the_raw_layer(aws):
    _, sqs, s3, urls = aws
    tx_id = str(uuid4())

    pub = Publicador(topic_arn=TOPIC_ARN)
    pub.publicar(_evento(tx_id, "HOLD"))
    pub.detener()

    leidos = atender_lote(sqs, urls["analitica"], "analitica", analytics.handler, espera_s=2)
    assert leidos == 1

    # La cola quedó vacía: el mensaje se borró tras guardarse.
    assert _leer_todo(sqs, urls["analitica"]) == []

    objetos = s3.list_objects_v2(Bucket=analytics.BUCKET, Prefix="raw/decisiones/")["Contents"]
    contenidos = [
        s3.get_object(Bucket=analytics.BUCKET, Key=o["Key"])["Body"].read().decode()
        for o in objetos
    ]
    assert any(tx_id in c for c in contenidos)


def test_a_decision_with_opens_case_reaches_the_cases_table(aws, monkeypatch):
    """HU-25: engine event → SNS → "casos" queue → cases consumer → PostgreSQL."""
    from sqlalchemy import select

    from services.consumers import cases
    from shared.cases import Case, create_schema
    from shared.tests.isolated_db import isolated_sessions

    _, sqs, _, urls = aws
    tx_id = str(uuid4())
    event = evento_decision(
        {
            "id": tx_id,
            "type": "RETIRO",
            "source_account_id": str(uuid4()),
            "destination_account_id": None,
            "amount": "950000.00",
            "currency": "COP",
            "transaction_date": "2026-10-13T20:00:00+00:00",
        },
        {
            "transaction_id": tx_id,
            "decision": "HOLD",
            "decision_reason": "Prueba",
            "rules_version": "0",
            "rules_triggered": ["mule"],
            "rule_versions": {"mule": 1},
            "opens_case": True,
            "amount_usd": "230.05",
            "risk_score": 50,
            "processed_at": "2026-10-13T20:00:00+00:00",
        },
    )

    with isolated_sessions("cases_localstack_test") as factory:
        with factory() as session:
            create_schema(session)
        monkeypatch.setattr(cases, "SessionLocal", factory)

        pub = Publicador(topic_arn=TOPIC_ARN)
        pub.publicar(event)
        pub.detener()

        leidos = atender_lote(sqs, urls["casos"], "casos", cases.handler, espera_s=2)
        assert leidos == 1
        assert _leer_todo(sqs, urls["casos"]) == []

        with factory() as session:
            [case] = session.scalars(select(Case)).all()
        assert str(case.transaction_id) == tx_id
        assert case.rules_triggered == ["mule"]
