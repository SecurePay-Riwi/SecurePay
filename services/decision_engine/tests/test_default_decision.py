"""HU-18 / RN-01: default decision when the rules take longer than the
timeout (CA-04: USD 30 is approved, USD 80 is held).

The slow rules are simulated by replacing _decide, so these tests need
Valkey (idempotency) but not PostgreSQL.
"""

import threading
import time
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from services.decision_engine import catalog, currency
from services.decision_engine import decision_service as ds
from services.decision_engine.schemas import TransactionRequest


class FakeSession:
    """Only what the timeout path touches."""

    def __init__(self):
        self.info = {}
        self.closed = threading.Event()

    def close(self):
        self.closed.set()


def _payload(amount: str, currency_code: str = "USD") -> TransactionRequest:
    return TransactionRequest(
        id=uuid4(),
        type="RETIRO",
        channel="CAJERO",
        source_account_id=uuid4(),
        amount=amount,
        currency=currency_code,
        source_balance_before="1000000",
        source_balance_after=str(Decimal("1000000") - Decimal(amount)),
        device_id=uuid4(),
        transaction_date=datetime.now(timezone.utc),
    )


def _rules_answer(decision: str, delay_s: float = 0):
    def fake_decide(session, payload, snapshot):
        time.sleep(delay_s)
        return {
            "transaction_id": str(payload.id),
            "decision": decision,
            "decision_reason": "rules answered",
            "rules_version": str(snapshot.version),
            "rules_triggered": [],
            "by_default": False,
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }

    return fake_decide


@pytest.fixture
def slow_rules(monkeypatch):
    """Rules that answer REJECT well after the timeout."""
    late = threading.Event()
    slow = _rules_answer("REJECT", delay_s=ds.TIMEOUT_MS / 1000 * 3)

    def decide(session, payload, snapshot):
        result = slow(session, payload, snapshot)
        late.set()
        return result

    monkeypatch.setattr(ds, "_decide", decide)
    return late


@pytest.mark.parametrize(
    ("amount", "expected"),
    [("30.00", "APPROVE"), ("49.99", "APPROVE"), ("50.00", "HOLD"), ("80.00", "HOLD")],
)
def test_timeout_applies_the_default_decision(slow_rules, amount, expected):
    session = FakeSession()

    start = time.perf_counter()
    result, replay = ds.process_transaction(session, _payload(amount))
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert replay is False
    assert result["decision"] == expected
    assert result["by_default"] is True
    assert result["rules_triggered"] == [ds.DEFAULT_RULE]
    assert elapsed_ms < 200


def test_rules_in_time_return_their_own_decision(monkeypatch):
    monkeypatch.setattr(ds, "_decide", _rules_answer("REJECT"))

    result, _ = ds.process_transaction(FakeSession(), _payload("80.00"))

    assert result["decision"] == "REJECT"
    assert result["by_default"] is False


def test_default_decision_is_never_reject():
    for amount in ("0.01", "50.00", "999999.00"):
        result = ds.default_decision(_payload(amount), catalog.current())
        assert result["decision"] in {"APPROVE", "HOLD"}


def test_threshold_is_in_usd_not_in_the_account_currency(slow_rules):
    # 100,000 COP is about USD 30; 300,000 COP is about USD 90.
    small, _ = ds.process_transaction(FakeSession(), _payload("100000.00", "COP"))
    large, _ = ds.process_transaction(FakeSession(), _payload("300000.00", "COP"))

    assert small["decision"] == "APPROVE"
    assert large["decision"] == "HOLD"


def test_resend_after_timeout_gets_the_same_decision(slow_rules):
    payload = _payload("80.00")

    first, _ = ds.process_transaction(FakeSession(), payload)
    assert slow_rules.wait(2)  # the late evaluation has finished
    second, replay = ds.process_transaction(FakeSession(), payload)

    assert replay is True
    assert second == first
    assert second["decision"] == "HOLD"


def test_late_evaluation_closes_the_session_and_is_not_published(
    slow_rules, eventos_publicados
):
    session = FakeSession()

    result, _ = ds.process_transaction(session, _payload("30.00"))

    # The request does not close it: the late thread still uses it.
    assert session.info[ds.LATE_SESSION] is True
    assert session.closed.wait(2)
    assert slow_rules.is_set()

    # Only the default decision went out, once.
    assert len(eventos_publicados) == 1
    assert eventos_publicados[0]["decision"] == result


def test_to_usd():
    assert currency.to_usd(Decimal("30"), "USD") == Decimal("30.00")
    assert currency.to_usd(Decimal("3317.65"), "COP") == Decimal("1.00")
    with pytest.raises(ValueError):
        currency.to_usd(Decimal("1"), "GBP")


def test_default_decision_records_the_version_of_its_rule():
    # RN-08: the default decision says which default_timeout entry set
    # its limit, like any rule that fires.
    base = catalog.current()
    rules = [
        r.model_copy(update={"rule_version": 3}) if r.code == ds.DEFAULT_RULE else r
        for r in base.rules
    ]
    snapshot = base.model_copy(update={"version": 7, "rules": rules})

    result = ds.default_decision(_payload("80.00"), snapshot)

    assert result["rules_version"] == "7"
    assert result["rule_versions"] == {ds.DEFAULT_RULE: 3}
