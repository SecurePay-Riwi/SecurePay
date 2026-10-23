"""RN-07 / HU-17: account takeover. A device change, a password change
and a transaction above USD 200 from the same account in less than an
hour are held.

Unit tests: RuleContext and RuleEntry are built by hand, without
PostgreSQL or Valkey.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from services.decision_engine import currency, history
from services.decision_engine.rules import REGISTRY, account_takeover
from services.decision_engine.rules.base import RuleContext
from services.decision_engine.schemas import Decision, TransactionRequest
from services.decision_engine.security_events import SecurityEvent
from shared.rule_catalog import RuleEntry, default_catalog

T = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)
RULE = default_catalog().get("account_takeover")


def change(type_, minutes_before):
    t = history.to_ms(T - timedelta(minutes=minutes_before))
    return SecurityEvent(str(uuid4()), type_, str(uuid4()), t)


BOTH = [change("DEVICE_CHANGE", 25), change("PASSWORD_CHANGE", 20)]


def context(events, amount="250.00", currency_="USD", type_="RETIRO"):
    """A transaction of `amount` at T whose account has these security
    events."""
    source = uuid4()
    body = {
        "id": str(uuid4()),
        "type": type_,
        "channel": "APP",
        "amount": amount,
        "currency": currency_,
        "device_id": str(uuid4()),
        "transaction_date": T.isoformat(),
    }
    if type_ != "RECARGA":
        body.update(
            source_account_id=str(source),
            source_balance_before="100000000",
            source_balance_after="0",
        )
    if type_ in ("P2P", "RECARGA"):
        body.update(
            destination_account_id=str(uuid4()),
            destination_balance_before="0",
            destination_balance_after=amount,
        )
    if type_ == "QR":
        body["merchant_id"] = str(uuid4())

    payload = TransactionRequest.model_validate(body)
    ctx = RuleContext(
        payload=payload,
        session=None,
        t_ms=history.to_ms(T),
        amount_usd=currency.to_usd(payload.amount, payload.currency),
    )
    # Preload the lazy property: no Valkey in these tests.
    ctx.__dict__["security_events"] = events
    return ctx


def test_rule_is_registered_and_in_the_default_catalog():
    assert REGISTRY["account_takeover"] is account_takeover
    assert RULE.action == "HOLD"
    assert RULE.typed_params().window_minutes == 60
    assert RULE.typed_params().min_amount_usd == Decimal(200)


def test_device_and_password_change_and_a_big_amount_fire():
    result = account_takeover.evaluate(context(BOTH), RULE)

    assert result.rule == "account_takeover"
    assert result.decision == Decision.HOLD
    assert result.reason == (
        "Account takeover: device and password changed in the last 60 minutes "
        "and the transaction is USD 250.00 (limit USD 200)."
    )


@pytest.mark.parametrize("type_", ["P2P", "QR", "RETIRO"])
def test_every_outgoing_type_is_checked(type_):
    assert account_takeover.evaluate(context(BOTH, type_=type_), RULE)


def test_a_recharge_is_not_checked():
    assert account_takeover.evaluate(context(BOTH, type_="RECARGA"), RULE) is None


@pytest.mark.parametrize(
    "events",
    [
        [change("DEVICE_CHANGE", 25)],
        [change("PASSWORD_CHANGE", 20)],
        [change("DEVICE_CHANGE", 25), change("DEVICE_CHANGE", 10)],
        [],
    ],
    ids=["only-device", "only-password", "two-device-changes", "no-changes"],
)
def test_two_of_three_signals_do_not_fire(events):
    assert account_takeover.evaluate(context(events), RULE) is None


def test_amount_of_exactly_200_does_not_fire():
    assert account_takeover.evaluate(context(BOTH, amount="200.00"), RULE) is None


def test_amount_just_above_200_fires():
    assert account_takeover.evaluate(context(BOTH, amount="200.01"), RULE)


def test_change_outside_the_window_does_not_count():
    events = [change("DEVICE_CHANGE", 60), change("PASSWORD_CHANGE", 20)]
    assert account_takeover.evaluate(context(events), RULE) is None


def test_change_just_inside_the_window_counts():
    events = [change("DEVICE_CHANGE", 59), change("PASSWORD_CHANGE", 20)]
    assert account_takeover.evaluate(context(events), RULE)


def test_change_after_the_transaction_does_not_count():
    events = [change("DEVICE_CHANGE", 25), change("PASSWORD_CHANGE", -5)]
    assert account_takeover.evaluate(context(events), RULE) is None


@pytest.mark.parametrize(
    ("amount", "currency_", "fires"),
    [
        # Fixed 2026-10-01 rates (currency.py): above and below USD 200.
        ("1200000", "COP", True),
        ("600000", "COP", False),
        ("40000", "JPY", True),
        ("20000", "JPY", False),
    ],
)
def test_amount_is_compared_in_usd(amount, currency_, fires):
    usd = currency.to_usd(Decimal(amount), currency_)
    assert (usd > 200) is fires, f"rates changed: {amount} {currency_} = USD {usd}"

    result = account_takeover.evaluate(
        context(BOTH, amount=amount, currency_=currency_), RULE
    )
    assert (result is not None) is fires


def test_thresholds_come_from_the_catalog():
    lower = RuleEntry(
        **{**RULE.model_dump(), "params": {"window_minutes": 60, "min_amount_usd": "100"}}
    )
    shorter = RuleEntry(
        **{**RULE.model_dump(), "params": {"window_minutes": 15, "min_amount_usd": "200"}}
    )

    assert account_takeover.evaluate(context(BOTH, amount="150.00"), RULE) is None
    assert account_takeover.evaluate(context(BOTH, amount="150.00"), lower)
    # The device change was 25 minutes ago: outside a 15-minute window.
    assert account_takeover.evaluate(context(BOTH), shorter) is None


def test_decision_and_case_come_from_the_catalog():
    reject = RuleEntry(**{**RULE.model_dump(), "action": "REJECT", "opens_case": True})

    result = account_takeover.evaluate(context(BOTH), reject)

    assert result.decision == Decision.REJECT
    assert result.opens_case is True
