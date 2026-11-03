"""The replay (contract C5): the engine's own rules over a history in
memory. Over the fixture day it gives the decisions the engine wrote in
raw/decisiones; it never reaches Valkey; and a replay does not leak its
history into the next one. No Java, PostgreSQL or Valkey needed."""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from services.analytics.replay import ReferenceData, ReplayDecision, decide_all, replay
from services.analytics.tests.conftest import FIXTURES
from services.decision_engine import currency, history, reference_data
from services.decision_engine.schemas import SecurityEventRequest, TransactionRequest
from shared.rule_catalog import default_catalog


@pytest.fixture(autouse=True)
def fixed_rates():
    currency.load({})
    yield
    currency.load({})


def _events() -> dict[str, dict]:
    events = {}
    for path in sorted((FIXTURES / "raw" / "decisiones").rglob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            e = json.loads(line)
            events.setdefault(e["transaction"]["id"], e)
    return events


def _security() -> list[SecurityEventRequest]:
    path = FIXTURES / "security_events.jsonl"
    return [
        SecurityEventRequest(**json.loads(x)) for x in path.read_text().splitlines()
    ]


def _history():
    events = _events()
    return events, [TransactionRequest(**e["transaction"]) for e in events.values()]


@pytest.fixture
def no_valkey(monkeypatch):
    def refuse():
        raise AssertionError("the replay must not reach Valkey")

    monkeypatch.setattr(history, "get_cache", refuse)
    monkeypatch.setattr(reference_data, "get_cache", refuse)


def test_the_replay_gives_the_engines_decisions(no_valkey):
    events, transactions = _history()

    decided = replay(
        default_catalog(),
        transactions,
        ReferenceData.from_fixtures(FIXTURES),
        _security(),
    )

    assert len(decided) == len(events)
    for d in decided:
        engine = events[d.transaction_id]["decision"]
        assert d == ReplayDecision(
            transaction_id=d.transaction_id,
            decision=engine["decision"],
            rules_triggered=tuple(engine["rules_triggered"]),
            risk_score=engine["risk_score"],
            opens_case=engine["opens_case"],
            rules_version=engine["rules_version"],
        )


def test_every_rule_fires_in_the_fixture_day(no_valkey):
    _, transactions = _history()

    decided = replay(
        default_catalog(),
        transactions,
        ReferenceData.from_fixtures(FIXTURES),
        _security(),
    )

    fired = {r for d in decided for r in d.rules_triggered}
    assert fired == {
        "restricted_list",
        "velocity",
        "mule",
        "shared_device",
        "splitting",
        "account_takeover",
        "default_timeout",
    }


def test_without_the_security_events_the_takeover_does_not_fire(no_valkey):
    _, transactions = _history()

    decided = replay(
        default_catalog(), transactions, ReferenceData.from_fixtures(FIXTURES)
    )

    assert "account_takeover" not in {r for d in decided for r in d.rules_triggered}


def test_each_replay_starts_with_an_empty_history(no_valkey):
    _, transactions = _history()
    ref = ReferenceData.from_fixtures(FIXTURES)

    first = replay(default_catalog(), transactions, ref, _security())
    second = replay(default_catalog(), transactions, ref, _security())

    assert first == second
    assert history._backend.get() is None
    assert reference_data._source.get() is None


def test_a_repeated_id_is_decided_once(no_valkey):
    _, transactions = _history()

    decided = replay(
        default_catalog(),
        transactions + transactions[:3],
        ReferenceData.from_fixtures(FIXTURES),
    )

    assert len(decided) == len(transactions)


def test_a_catalog_change_changes_the_replay(no_valkey):
    _, transactions = _history()
    old = default_catalog().model_copy(
        update={
            "rules": [
                r.model_copy(update={"action": "APPROVE"})
                if r.code == "splitting"
                else r
                for r in default_catalog().rules
            ]
        }
    )
    ref = ReferenceData.from_fixtures(FIXTURES)

    now = {d.transaction_id: d for d in replay(default_catalog(), transactions, ref)}
    before = {d.transaction_id: d for d in replay(old, transactions, ref)}

    changed = [t for t in now if now[t].decision != before[t].decision]
    assert len(changed) == 2  # the two splits: HOLD now, APPROVE before (D2)
    assert {now[t].decision for t in changed} == {"HOLD"}
    assert all(before[t].opens_case for t in changed)


def test_a_currency_that_is_not_the_accounts_is_left_out(no_valkey):
    account = str(uuid4())
    ref = ReferenceData(
        {
            account: {
                "currency": "COP",
                "user_id": "u",
                "document": "1",
                "status": "activa",
            }
        }
    )
    tx = TransactionRequest(
        id=uuid4(),
        type="RETIRO",
        channel="CAJERO",
        source_account_id=account,
        amount="10.00",
        currency="USD",
        source_balance_before="100.00",
        source_balance_after="90.00",
        device_id=uuid4(),
        transaction_date=datetime(2026, 10, 5, tzinfo=UTC),
    )

    assert decide_all(default_catalog(), [tx], ref) == []


def test_reference_data_answers_like_the_cache():
    ref = ReferenceData.from_fixtures(FIXTURES)
    account_id, data = next(iter(ref.accounts.items()))

    account = ref.get_account(account_id)
    assert (account.id, account.currency, account.document) == (
        account_id,
        data["currency"],
        data["document"],
    )
    assert ref.get_account(uuid4()) is None
    assert ref.merchant_exists(next(iter(ref.merchants)))
    assert not ref.merchant_exists(uuid4())
    assert ref.on_restricted_list(set(ref.restricted_documents)) is True
    assert ref.on_restricted_list({"0"}) is False


def test_reference_data_from_the_database_has_the_seed():
    from sqlalchemy.exc import OperationalError

    from shared.db import SessionLocal

    try:
        with SessionLocal() as session:
            ref = ReferenceData.from_database(session)
    except OperationalError:
        pytest.skip("PostgreSQL is not available")
    if not ref.accounts:
        pytest.skip("the seed is not loaded")

    assert ref.merchants and ref.restricted_documents
    assert all(d.isdigit() for d in ref.restricted_documents)


def test_security_events_after_the_transaction_do_not_count(no_valkey):
    account = str(uuid4())
    ref = ReferenceData(
        {
            account: {
                "currency": "USD",
                "user_id": "u",
                "document": "1",
                "status": "activa",
            }
        },
        {"m"},
    )
    when = datetime(2026, 10, 5, 12, tzinfo=UTC)
    tx = TransactionRequest(
        id=uuid4(),
        type="RETIRO",
        channel="CAJERO",
        source_account_id=account,
        amount="500.00",
        currency="USD",
        source_balance_before="10000.00",
        source_balance_after="9500.00",
        device_id=uuid4(),
        transaction_date=when,
    )
    events = [
        SecurityEventRequest(
            id=uuid4(),
            type=kind,
            user_id=uuid4(),
            account_id=account,
            device_id=uuid4(),
            event_date=when + delta,
        )
        for kind, delta in (
            ("DEVICE_CHANGE", timedelta(minutes=-20)),
            ("PASSWORD_CHANGE", timedelta(minutes=5)),
        )
    ]

    [d] = replay(default_catalog(), [tx], ref, events)

    assert "account_takeover" not in d.rules_triggered
