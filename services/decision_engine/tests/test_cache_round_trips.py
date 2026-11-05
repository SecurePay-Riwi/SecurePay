"""A decision reads and writes the cache in two round trips (HU-60): the
accounts and the merchant in one pipeline, the history and the
restricted list in another. The answers are the same as one command at
a time."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
import valkey

from services.decision_engine import catalog, history, reference_data
from services.decision_engine import decision_service as ds
from services.decision_engine.schemas import TransactionRequest
from shared.cache import get_cache

NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


@pytest.fixture
def keys():
    """Keys written by the test, deleted at the end. Skipped without Valkey."""
    try:
        get_cache().ping()
    except valkey.exceptions.ConnectionError:
        pytest.skip("Valkey is not available at VALKEY_URL")
    written = []
    yield written
    for key in written:
        get_cache().delete(key)


def _account(keys, currency="USD", document="5550001"):
    account_id = uuid4()
    key = reference_data.account_key(account_id)
    get_cache().hset(
        key,
        mapping={
            "currency": currency,
            "user_id": str(uuid4()),
            "document": document,
            "status": "activa",
        },
    )
    keys.append(key)
    return account_id


def test_lookup_answers_like_one_read_at_a_time(keys):
    known = _account(keys)
    merchant_id = uuid4()
    get_cache().hset(reference_data.merchant_key(merchant_id), "status", "activo")
    keys.append(reference_data.merchant_key(merchant_id))
    missing = uuid4()

    accounts, merchant = reference_data.lookup((known, missing, None), merchant_id)

    assert accounts == {
        known: reference_data.get_account(known),
        missing: None,
    }
    assert merchant is True
    assert reference_data.lookup((known,), uuid4())[1] is False
    assert reference_data.lookup((known,))[1] is None


def test_run_returns_what_each_record_function_returns(keys):
    account, device = str(uuid4()), str(uuid4())
    keys += [
        history.outgoing_key(account),
        history.incoming_key(account),
        history.device_key(device),
    ]

    outgoing, incoming, devices = history.run(
        [
            history.outgoing_record(account, "t1", "P2P", "10.00", NOW),
            history.incoming_record(account, "t2", "s", "5.00", NOW),
            history.device_record(device, account, NOW),
        ]
    )

    assert outgoing == [history.Outgoing("t1", "P2P", "10.00", history.to_ms(NOW))]
    assert incoming is None
    assert devices == [history.DeviceUse(account, history.to_ms(NOW))]
    assert [i.id for i in history.incoming(account)] == ["t2"]


def test_run_loads_the_script_when_valkey_lost_it(keys):
    # A restart or a failover empties Valkey's script cache: the
    # pipeline's EVALSHA gets NoScriptError and the record is written again.
    account = str(uuid4())
    keys.append(history.outgoing_key(account))
    get_cache().script_flush()

    (outgoing,) = history.run(
        [history.outgoing_record(account, "t1", "QR", "3.00", NOW)]
    )

    assert [o.id for o in outgoing] == ["t1"]


class _Counting:
    """The cache client, counting round trips: each command, and each
    pipeline however many commands it carries."""

    def __init__(self, client):
        self._client = client
        self.round_trips = 0

    def pipeline(self, *args, **kwargs):
        pipe = self._client.pipeline(*args, **kwargs)
        execute = pipe.execute

        def counted(*a, **k):
            self.round_trips += 1
            return execute(*a, **k)

        pipe.execute = counted
        return pipe

    def __getattr__(self, name):
        attr = getattr(self._client, name)
        if not callable(attr) or name == "register_script":
            return attr

        def counted(*a, **k):
            self.round_trips += 1
            return attr(*a, **k)

        return counted


def test_a_transfer_takes_two_round_trips(keys, monkeypatch):
    source, destination = _account(keys), _account(keys, document="5550002")
    device = uuid4()
    keys += [
        history.outgoing_key(source),
        history.incoming_key(destination),
        history.device_key(device),
    ]
    counting = _Counting(get_cache())
    for module in (reference_data, history, ds):
        monkeypatch.setattr(module, "get_cache", lambda: counting)
    history._valkey._registered()  # the script is registered once per process

    payload = TransactionRequest(
        id=uuid4(),
        type="P2P",
        channel="APP",
        source_account_id=source,
        destination_account_id=destination,
        amount="10.00",
        currency="USD",
        source_balance_before="100.00",
        source_balance_after="90.00",
        destination_balance_before="0.00",
        destination_balance_after="10.00",
        device_id=device,
        transaction_date=datetime.now(UTC),
    )
    result = ds._decide(payload, catalog.current())

    assert result["by_default"] is False
    assert counting.round_trips == 2
