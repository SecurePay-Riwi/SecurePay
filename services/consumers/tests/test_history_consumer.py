"""History consumer (HU-28) against an empty PostgreSQL schema of its own.

Needs PostgreSQL (DATABASE_URL).
"""

import json
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from services.consumers import history
from shared.cases import AccountTransaction, create_schema
from shared.events import evento_decision
from shared.tests.isolated_db import down_sessions, isolated_sessions


@pytest.fixture
def sessions(monkeypatch):
    with isolated_sessions("history_consumer_test") as factory:
        with factory() as session:
            create_schema(session)
        monkeypatch.setattr(history, "SessionLocal", factory)
        yield factory


def _event(
    tx_type="P2P",
    source="new",
    destination="new",
    merchant=None,
    decision="APPROVE",
    rules=(),
    **decision_fields,
):
    tx_id = str(uuid4())
    transaction = {
        "id": tx_id,
        "type": tx_type,
        "channel": "APP",
        "source_account_id": str(uuid4()) if source == "new" else source,
        "destination_account_id": str(uuid4()) if destination == "new" else destination,
        "merchant_id": merchant,
        "amount": "950000.00",
        "currency": "COP",
        "device_id": str(uuid4()),
        "transaction_date": "2026-10-13T20:00:00Z",
    }
    result = {
        "transaction_id": tx_id,
        "decision": decision,
        "decision_reason": "Test decision.",
        "rules_version": "3",
        "rules_triggered": list(rules),
        "rule_versions": {rule: 1 for rule in rules},
        "opens_case": False,
        "amount_usd": "230.05",
        "risk_score": 40,
        "by_default": False,
        "processed_at": "2026-10-13T20:00:00.010000+00:00",
    }
    result.update(decision_fields)
    return evento_decision(transaction, result)


def _batch(*bodies):
    return {
        "Records": [
            {
                "messageId": f"m{i}",
                "receiptHandle": f"r{i}",
                "body": body if isinstance(body, str) else json.dumps(body),
            }
            for i, body in enumerate(bodies)
        ]
    }


def _rows(factory):
    with factory() as session:
        return {
            row.direction: row
            for row in session.scalars(select(AccountTransaction)).all()
        }


def _count(factory):
    with factory() as session:
        return session.scalar(select(func.count()).select_from(AccountTransaction))


def test_a_transfer_writes_out_for_the_source_and_in_for_the_destination(sessions):
    event = _event(decision="HOLD", rules=("velocity",))

    assert history.handler(_batch(event)) == {"batchItemFailures": []}

    tx = event["transaction"]
    rows = _rows(sessions)
    assert set(rows) == {"OUT", "IN"}
    out, in_ = rows["OUT"], rows["IN"]
    assert out.account_id == UUID(tx["source_account_id"])
    assert out.counterparty_account_id == UUID(tx["destination_account_id"])
    assert in_.account_id == UUID(tx["destination_account_id"])
    assert in_.counterparty_account_id == UUID(tx["source_account_id"])
    # The device only on the main account's row, as dev:{device}.
    assert out.device_id == UUID(tx["device_id"])
    assert in_.device_id is None
    for row in (out, in_):
        assert row.transaction_id == UUID(tx["id"])
        assert row.type == "P2P" and row.channel == "APP"
        assert row.amount == Decimal("950000.00") and row.currency == "COP"
        assert row.amount_usd == Decimal("230.05")
        assert row.decision == "HOLD"
        assert row.rules_triggered == ["velocity"]
        assert row.risk_score == 40
        assert row.transaction_date == datetime.fromisoformat("2026-10-13T20:00:00+00:00")
        assert row.processed_at == datetime.fromisoformat("2026-10-13T20:00:00.010000+00:00")


def test_the_same_event_twice_writes_nothing_twice(sessions):
    event = _event()

    assert history.handler(_batch(event, event)) == {"batchItemFailures": []}
    assert history.handler(_batch(event)) == {"batchItemFailures": []}

    assert _count(sessions) == 2


def test_a_withdrawal_has_only_the_source(sessions):
    event = _event(tx_type="RETIRO", destination=None)

    history.handler(_batch(event))

    [out] = _rows(sessions).values()
    assert out.direction == "OUT"
    assert out.counterparty_account_id is None
    assert out.device_id == UUID(event["transaction"]["device_id"])


def test_a_qr_payment_keeps_the_merchant(sessions):
    merchant = str(uuid4())
    event = _event(tx_type="QR", destination=None, merchant=merchant)

    history.handler(_batch(event))

    [out] = _rows(sessions).values()
    assert out.merchant_id == UUID(merchant)


def test_a_top_up_belongs_to_the_destination_with_its_device(sessions):
    event = _event(tx_type="RECARGA", source=None)

    history.handler(_batch(event))

    [in_] = _rows(sessions).values()
    assert in_.direction == "IN"
    assert in_.account_id == UUID(event["transaction"]["destination_account_id"])
    # The destination is the main account of a top-up.
    assert in_.device_id == UUID(event["transaction"]["device_id"])


def test_a_reject_is_written_too(sessions):
    event = _event(decision="REJECT", rules=("restricted_list",), risk_score=100)

    history.handler(_batch(event))

    assert {row.decision for row in _rows(sessions).values()} == {"REJECT"}


def test_an_event_without_amount_usd_is_written_with_null(sessions):
    event = _event()
    del event["decision"]["amount_usd"]

    assert history.handler(_batch(event)) == {"batchItemFailures": []}

    assert {row.amount_usd for row in _rows(sessions).values()} == {None}


def test_a_broken_event_fails_alone(sessions):
    good = _event()
    no_amount = _event()
    del no_amount["transaction"]["amount"]
    bad_account = _event(source="not-a-uuid")
    naive_date = _event()
    naive_date["transaction"]["transaction_date"] = "2026-10-13T20:00:00"

    result = history.handler(_batch(good, no_amount, bad_account, naive_date, "not json"))

    assert result == {
        "batchItemFailures": [
            {"itemIdentifier": "m4"},
            {"itemIdentifier": "m1"},
            {"itemIdentifier": "m2"},
            {"itemIdentifier": "m3"},
        ]
    }
    assert _count(sessions) == 2


def test_postgresql_down_returns_the_whole_batch(monkeypatch):
    down = down_sessions()
    monkeypatch.setattr(history, "SessionLocal", down)

    result = history.handler(_batch(_event(), "not json", _event()))

    assert result == {
        "batchItemFailures": [
            {"itemIdentifier": "m1"},
            {"itemIdentifier": "m0"},
            {"itemIdentifier": "m2"},
        ]
    }
