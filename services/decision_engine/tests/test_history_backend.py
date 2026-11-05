"""The history's backend seam (sprint 6 step 0, contract C5): the engine
keeps writing and reading Valkey, and history.use_backend() lets the
analytics replay keep the same sorted sets in memory, with the same
order and the same trim.

The comparison with Valkey needs it running (skips otherwise); the rest
needs nothing.
"""

import threading
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import valkey

from services.decision_engine import history, reference_data, security_events
from services.decision_engine.history import InMemoryHistory, ValkeyHistory
from services.decision_engine.reference_data import Account
from shared.cache import get_cache

BASE = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


def _steps(account):
    """Outgoing movements out of order, one older than the retention,
    and a repeated member that moves."""
    return [
        ("a", BASE),
        ("b", BASE + timedelta(minutes=5)),
        ("c", BASE - timedelta(minutes=1)),
        ("a", BASE + timedelta(minutes=7)),  # the same member moves
        ("d", BASE + timedelta(hours=30)),  # trims everything before 6:00 +1 day
        ("e", BASE + timedelta(hours=7)),  # older than the retention: trimmed at once
    ]


def _run(account):
    replies = []
    for member, when in _steps(account):
        replies.append(
            history.record(
                history.outgoing_key(account),
                member,
                when,
                history.OUT_MS,
                return_history=True,
            )
        )
    return replies, history.read(history.outgoing_key(account))


def test_the_engine_uses_valkey_by_default():
    assert isinstance(history.backend(), ValkeyHistory)


def test_in_memory_keeps_valkeys_order_and_trim():
    try:
        get_cache().ping()
    except valkey.exceptions.ConnectionError:
        pytest.skip("Valkey is not available at VALKEY_URL")
    account = str(uuid4())
    try:
        in_valkey, read_valkey = _run(account)
    finally:
        get_cache().delete(history.outgoing_key(account))

    with history.use_backend(InMemoryHistory()):
        in_memory, read_memory = _run(account)

    def plain(raw):
        return [(m, int(float(t))) for m, t in history._pairs(raw)]

    assert [plain(r) for r in in_memory] == [plain(r) for r in in_valkey]
    assert [(m, int(t)) for m, t in read_memory] == [
        (m, int(t)) for m, t in read_valkey
    ]


def test_use_backend_writes_nothing_to_valkey(monkeypatch):
    def refuse():
        raise AssertionError("Valkey must not be reached")

    monkeypatch.setattr(history, "get_cache", refuse)
    account = str(uuid4())

    with history.use_backend(InMemoryHistory()):
        out = history.record_outgoing(account, "t1", "P2P", "10.00", BASE)
        history.record_incoming(account, "t2", "s", "5.00", BASE)
        devices = history.record_device("dev", account, BASE)
        incoming = history.incoming(account)
        assert security_events.recent(account) == []

    assert [o.id for o in out] == ["t1"]
    assert [i.id for i in incoming] == ["t2"]
    assert [d.account for d in devices] == [account]


def test_use_backend_is_undone_after_the_block_and_on_errors():
    memory = InMemoryHistory()
    with pytest.raises(RuntimeError):
        with history.use_backend(memory):
            assert history.backend() is memory
            raise RuntimeError("boom")

    assert isinstance(history.backend(), ValkeyHistory)


def test_use_backend_belongs_to_its_thread():
    seen = []
    with history.use_backend(InMemoryHistory()):
        worker = threading.Thread(target=lambda: seen.append(history.backend()))
        worker.start()
        worker.join()

    assert isinstance(seen[0], ValkeyHistory)


def test_use_source_replaces_the_cache_reads(monkeypatch):
    def refuse():
        raise AssertionError("Valkey must not be reached")

    class Source:
        def get_account(self, account_id):
            return Account(str(account_id), "USD", "u", "1", "activa")

        def merchant_exists(self, merchant_id):
            return merchant_id == "m"

        def on_restricted_list(self, documents):
            return "1" in documents

    monkeypatch.setattr(reference_data, "get_cache", refuse)
    with reference_data.use_source(Source()):
        assert reference_data.get_account("a").currency == "USD"
        assert reference_data.merchant_exists("m") is True
        assert reference_data.on_restricted_list({"1"}) is True

    assert reference_data._source.get() is None


def test_in_memory_returns_the_newest_like_valkey():
    try:
        get_cache().ping()
    except valkey.exceptions.ConnectionError:
        pytest.skip("Valkey is not available at VALKEY_URL")
    account = str(uuid4())
    key = history.outgoing_key(account)
    memory = InMemoryHistory()
    try:
        for minute in [4, 1, 3, 0, 2]:
            t = 1_000_000 + minute * 60_000
            for backend in (history._valkey, memory):
                backend.record(key, f"tx{minute}|P2P|1", t, history.OUT_MS, True, 3)
        in_valkey = history._valkey.record(
            key, "tx9|P2P|1", 9_000_000, history.OUT_MS, True, 3
        )
    finally:
        get_cache().delete(key)
    in_memory = memory.record(key, "tx9|P2P|1", 9_000_000, history.OUT_MS, True, 3)

    def plain(raw):
        return [(m, int(float(t))) for m, t in history._pairs(raw)]

    assert plain(in_memory) == plain(in_valkey)
    assert [m for m, _ in plain(in_valkey)] == ["tx3|P2P|1", "tx4|P2P|1", "tx9|P2P|1"]
