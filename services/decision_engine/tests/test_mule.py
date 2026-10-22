"""HU-13 / RN-03: mule account. Transfers from 3 or more different
accounts, then a withdrawal of 80 % or more of the balance, all in less
than 30 minutes, are held and open a case.

Needs the seed loaded in PostgreSQL and Valkey.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func

from services.decision_engine.rules import mule
from services.decision_engine.history import Incoming
from services.decision_engine.main import app
from shared.cache import get_cache
from shared.config import MONEDA_DECIMALES
from shared.db import get_session
from shared.models import Cuenta, DispositivoCuenta, ListaRestrictiva, Usuario

client = TestClient(app)

BALANCE = Decimal("1000")


@pytest.fixture
def accounts():
    """Four active accounts in the same currency, none on the restricted
    list: the first is the mule, the rest send it money. Their history
    starts empty."""
    session = get_session()

    try:
        rows = (
            session.query(Cuenta, DispositivoCuenta.dispositivo_id)
            .join(DispositivoCuenta, DispositivoCuenta.cuenta_id == Cuenta.id)
            .join(Usuario, Usuario.id == Cuenta.user_id)
            .outerjoin(
                ListaRestrictiva,
                ListaRestrictiva.documento
                == func.regexp_replace(Usuario.documento, r"\D", "", "g"),
            )
            .filter(Cuenta.estado == "activa", ListaRestrictiva.id.is_(None))
            .order_by(Cuenta.id)
            .all()
        )
    finally:
        session.close()

    by_currency = {}
    for account, device in rows:
        same = by_currency.setdefault(account.moneda, {})
        same.setdefault(account.id, (account, device))

    group = next((g for g in by_currency.values() if len(g) >= 4), None)
    assert group is not None, "The seed needs 4 active accounts in one currency"

    chosen = list(group.values())[:4]
    for account, _ in chosen:
        get_cache().delete(f"out:{account.id}", f"in:{account.id}")
    return chosen


def _money(amount, currency) -> str:
    return str(Decimal(amount).quantize(Decimal(1).scaleb(-MONEDA_DECIMALES[currency])))


def _transfer(sender, receiver, amount, date) -> dict:
    (src, device), (dst, _) = sender, receiver
    amount = Decimal(amount)
    return {
        "id": str(uuid4()),
        "type": "P2P",
        "channel": "APP",
        "source_account_id": str(src.id),
        "destination_account_id": str(dst.id),
        "amount": _money(amount, src.moneda),
        "currency": src.moneda,
        "source_balance_before": _money(BALANCE, src.moneda),
        "source_balance_after": _money(BALANCE - amount, src.moneda),
        "destination_balance_before": _money(BALANCE, src.moneda),
        "destination_balance_after": _money(BALANCE + amount, src.moneda),
        "device_id": str(device),
        "transaction_date": date.isoformat(),
    }


def _withdrawal(account, pct, date, balance=BALANCE, tx_type="RETIRO") -> dict:
    acc, device = account
    amount = balance * Decimal(pct) / 100
    return {
        "id": str(uuid4()),
        "type": tx_type,
        "channel": "CAJERO",
        "source_account_id": str(acc.id),
        "amount": _money(amount, acc.moneda),
        "currency": acc.moneda,
        "source_balance_before": _money(balance, acc.moneda),
        "source_balance_after": _money(balance - amount, acc.moneda),
        "device_id": str(device),
        "transaction_date": date.isoformat(),
    }


def _post(payload) -> dict:
    response = client.post("/transactions", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def _receive(accounts, minutes, senders=None):
    """The mule receives one transfer per minute in `minutes`, each from
    the sender at the same position in `senders` (default: one each)."""
    mule_account, others = accounts[0], accounts[1:]
    senders = senders or others
    base = datetime.now(timezone.utc)

    for sender, m in zip(senders, minutes):
        decision = _post(_transfer(sender, mule_account, 100, base + timedelta(minutes=m)))
        assert decision["decision"] == "APPROVE"
    return base


def test_mule_pattern_is_held_and_opens_a_case(accounts, eventos_publicados):
    # The generator's pattern: 3 senders, 90 % withdrawn at minute 20.
    base = _receive(accounts, [2, 6, 10])

    decision = _post(_withdrawal(accounts[0], 90, base + timedelta(minutes=20)))

    assert decision["decision"] == "HOLD"
    assert decision["rules_triggered"] == ["mule"]
    assert decision["opens_case"] is True
    assert "3 accounts" in decision["decision_reason"]
    assert eventos_publicados[-1]["decision"]["opens_case"] is True


def test_two_senders_are_not_a_mule(accounts):
    # The generator's control case.
    base = _receive(accounts, [2, 6])

    decision = _post(_withdrawal(accounts[0], 90, base + timedelta(minutes=20)))

    assert decision["decision"] == "APPROVE"
    assert decision["opens_case"] is False


def test_same_sender_three_times_counts_once(accounts):
    sender = accounts[1]
    base = _receive(accounts, [2, 6, 10], senders=[sender] * 3)

    decision = _post(_withdrawal(accounts[0], 90, base + timedelta(minutes=20)))

    assert decision["decision"] == "APPROVE"


@pytest.mark.parametrize(("pct", "expected"), [("79.9", "APPROVE"), ("80", "HOLD")])
def test_withdrawal_threshold_is_80_percent(accounts, pct, expected):
    base = _receive(accounts, [2, 6, 10])

    decision = _post(_withdrawal(accounts[0], pct, base + timedelta(minutes=20)))

    assert decision["decision"] == expected


def test_transfers_older_than_30_minutes_do_not_count(accounts):
    # The first transfer is 31 minutes before the withdrawal.
    base = _receive(accounts, [0, 20, 25])

    decision = _post(_withdrawal(accounts[0], 90, base + timedelta(minutes=31)))

    assert decision["decision"] == "APPROVE"


def test_transfer_recorded_after_the_withdrawal_time_does_not_count(accounts):
    # Arrives first but happened after the withdrawal (out of order).
    base = _receive(accounts, [2, 6, 25])

    decision = _post(_withdrawal(accounts[0], 90, base + timedelta(minutes=20)))

    assert decision["decision"] == "APPROVE"


def test_moving_the_money_by_p2p_is_not_a_withdrawal(accounts):
    base = _receive(accounts, [2, 6, 10])
    payload = _transfer(accounts[0], accounts[1], 900, base + timedelta(minutes=20))

    decision = _post(payload)

    assert decision["decision"] == "APPROVE"


def test_velocity_hold_does_not_open_a_case(accounts):
    sender, receiver = accounts[1], accounts[0]
    base = datetime.now(timezone.utc)

    decisions = [
        _post(_transfer(sender, receiver, 1, base + timedelta(minutes=m)))
        for m in range(6)
    ]

    assert decisions[-1]["rules_triggered"] == ["velocity"]
    assert decisions[-1]["opens_case"] is False


# Unit tests of the window and the threshold, without Valkey.


def _incoming(*pairs):
    return [Incoming(f"tx{i}", sender, "1", t) for i, (sender, t) in enumerate(pairs)]


def test_senders_counts_different_accounts_inside_the_window():
    window_ms = 30 * 60 * 1000
    t = window_ms * 2
    incoming = _incoming(
        ("a", t - window_ms),      # exactly 30 min before: out
        ("b", t - window_ms + 1),  # just inside
        ("b", t - 1000),
        ("c", t),
        ("d", t + 1),                   # after the withdrawal: out
    )

    assert mule.senders(incoming, t, 30) == 2


def test_withdraws_enough_compares_with_the_balance_before():
    assert mule.withdraws_enough(Decimal("80"), Decimal("100"), Decimal("80"))
    assert not mule.withdraws_enough(Decimal("79.99"), Decimal("100"), Decimal("80"))
    assert mule.withdrawn_pct(Decimal("90"), Decimal("100")) == Decimal("90.0")
    assert mule.withdrawn_pct(Decimal("5"), Decimal("0")) == Decimal("100")
