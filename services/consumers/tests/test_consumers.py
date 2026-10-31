"""Consumidores y runner, con S3 y SQS de mentira (no necesitan LocalStack)."""

import json

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from services.consumers import analytics, cases, history
from services.consumers.runner import atender_lote, prepare_database
from shared.events import evento_decision
from shared.tests.isolated_db import isolated_sessions


def _evento(n, decision="APPROVE"):
    return evento_decision(
        {"id": f"tx-{n}", "amount": "10.00", "currency": "USD"},
        {
            "transaction_id": f"tx-{n}",
            "decision": decision,
            "decision_reason": "Prueba",
            "processed_at": "2026-10-13T20:00:00+00:00",
        },
    )


def _lote(*cuerpos):
    return {
        "Records": [
            {"messageId": f"m{i}", "receiptHandle": f"r{i}", "body": cuerpo}
            for i, cuerpo in enumerate(cuerpos)
        ]
    }


class S3Falso:
    def __init__(self, falla=False):
        self.objetos = {}
        self.falla = falla

    def put_object(self, Bucket, Key, Body, ContentType):
        if self.falla:
            raise ConnectionError("S3 no responde")
        self.objetos[(Bucket, Key)] = Body.decode("utf-8")


def test_analytics_writes_the_batch_as_json_lines(monkeypatch):
    s3 = S3Falso()
    monkeypatch.setattr(analytics, "_s3", s3)

    resultado = analytics.handler(
        _lote(json.dumps(_evento(1)), json.dumps(_evento(2)))
    )

    assert resultado == {"batchItemFailures": []}
    [(bucket, clave)] = s3.objetos
    assert bucket == analytics.BUCKET
    assert clave.startswith("raw/decisiones/fecha=")
    lineas = s3.objetos[(bucket, clave)].splitlines()
    assert [json.loads(l)["transaction"]["id"] for l in lineas] == ["tx-1", "tx-2"]


def test_a_broken_message_fails_alone(monkeypatch):
    s3 = S3Falso()
    monkeypatch.setattr(analytics, "_s3", s3)

    resultado = analytics.handler(_lote(json.dumps(_evento(1)), "no es json"))

    # Solo el dañado vuelve a la cola; el otro quedó guardado.
    assert resultado == {"batchItemFailures": [{"itemIdentifier": "m1"}]}
    assert len(s3.objetos) == 1


def test_unknown_event_version_is_rejected():
    evento = _evento(1)
    evento["event_version"] = 99

    resultado = history.handler(_lote(json.dumps(evento)))

    assert resultado == {"batchItemFailures": [{"itemIdentifier": "m0"}]}


def test_analytics_retries_the_whole_batch_when_s3_fails(monkeypatch):
    monkeypatch.setattr(analytics, "_s3", S3Falso(falla=True))

    resultado = analytics.handler(
        _lote(json.dumps(_evento(1)), json.dumps(_evento(2)))
    )

    assert resultado == {
        "batchItemFailures": [{"itemIdentifier": "m0"}, {"itemIdentifier": "m1"}]
    }


def test_cases_acknowledges_events_that_open_no_case():
    lote = _lote(json.dumps(_evento(1, "HOLD")), json.dumps(_evento(2)))

    # No opens_case: nothing to write, PostgreSQL is not touched. The
    # history consumer writes every event (test_history_consumer.py).
    assert cases.handler(lote) == {"batchItemFailures": []}


class SqsFalso:
    def __init__(self, cuerpos):
        self.mensajes = [
            {"MessageId": f"m{i}", "ReceiptHandle": f"r{i}", "Body": c}
            for i, c in enumerate(cuerpos)
        ]
        self.borrados = []

    def receive_message(self, **kwargs):
        return {"Messages": self.mensajes}

    def delete_message_batch(self, QueueUrl, Entries):
        self.borrados += [e["ReceiptHandle"] for e in Entries]


def test_runner_deletes_only_successful_messages():
    sqs = SqsFalso(["ok", "mal", "ok"])

    def handler(event, context):
        return {
            "batchItemFailures": [
                {"itemIdentifier": r["messageId"]}
                for r in event["Records"]
                if r["body"] == "mal"
            ]
        }

    leidos = atender_lote(sqs, "url", "prueba", handler, espera_s=0)

    assert leidos == 3
    assert sqs.borrados == ["r0", "r2"]


def test_runner_keeps_the_batch_when_the_handler_crashes():
    sqs = SqsFalso(["ok", "ok"])

    def handler(event, context):
        raise RuntimeError("se cayó")

    atender_lote(sqs, "url", "prueba", handler, espera_s=0)

    assert sqs.borrados == []


def test_decision_without_required_fields_is_rejected():
    evento = _evento(1)
    del evento["decision"]["decision_reason"]

    resultado = cases.handler(_lote(json.dumps(evento)))

    assert resultado == {"batchItemFailures": [{"itemIdentifier": "m0"}]}


def test_runner_creates_the_case_tables_before_reading():
    down = sessionmaker(bind=create_engine("postgresql+psycopg://x:x@127.0.0.1:1/x"))
    with isolated_sessions("consumers_runner_test") as factory:
        attempts = []

        def first_down_then_up():
            attempts.append(1)
            return (down if len(attempts) == 1 else factory)()

        prepare_database(first_down_then_up, wait_s=0)

        with factory() as session:
            assert "cases" in inspect(session.connection()).get_table_names()
    assert len(attempts) == 2
