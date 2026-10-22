"""HU-14 / RN-04: shared device. A device used by more than 3 accounts
in 30 days raises the risk score of every account that uses it.

The unit tests build RuleContext and RuleEntry by hand. The last ones
need Valkey (record_device) and the seed in PostgreSQL (the API).
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
import valkey
from fastapi.testclient import TestClient
from sqlalchemy import func

from services.decision_engine import history
from services.decision_engine.history import DeviceUse, device_key, record_device, to_ms
from services.decision_engine.main import app
from services.decision_engine.rules import shared_device
from services.decision_engine.rules.base import RuleContext
from services.decision_engine.schemas import Decision, TransactionRequest
from shared.cache import get_cache
from shared.config import MONEDA_DECIMALES
from shared.db import get_session
from shared.models import Cuenta, ListaRestrictiva, Usuario
from shared.rule_catalog import RuleEntry, default_catalog

BASE = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)
DAY_MS = 24 * 3600 * 1000

client = TestClient(app)


def _rule(**params) -> RuleEntry:
    entry = default_catalog().get("shared_device")
    return entry.model_copy(update={"params": {**entry.params, **params}})


def _context(*days_ago: float) -> RuleContext:
    """A transaction at BASE on a device that one account per value of
    `days_ago` used that many days before."""
    payload = TransactionRequest(
        id=uuid4(), type="RETIRO", channel="CAJERO",
        source_account_id=uuid4(), amount="10.00", currency="USD",
        source_balance_before="100.00", source_balance_after="90.00",
        device_id=uuid4(), transaction_date=BASE,
    )
    t = to_ms(BASE)
    return RuleContext(
        payload=payload,
        session=None,
        t_ms=t,
        amount_usd=Decimal("10.00"),
        device_accounts=[
            DeviceUse(f"account-{i}", int(t - d * DAY_MS))
            for i, d in enumerate(days_ago)
        ],
    )


def test_three_accounts_do_not_fire():
    assert shared_device.evaluate(_context(0, 1, 2), _rule()) is None


def test_four_accounts_fire_with_the_catalog_decision_and_score():
    result = shared_device.evaluate(_context(0, 1, 2, 3), _rule())

    assert result.rule == "shared_device"
    assert result.decision == Decision.APPROVE
    assert result.score == 30
    assert result.opens_case is False
    assert result.reason == (
        "Shared device: used by 4 accounts in the last 30 days (limit 3)."
    )


def test_an_account_seen_31_days_ago_does_not_count():
    assert shared_device.evaluate(_context(0, 1, 2, 31), _rule()) is None


def test_an_account_seen_exactly_window_days_ago_does_not_count():
    assert shared_device.evaluate(_context(0, 1, 2, 30), _rule()) is None


def test_an_account_seen_after_the_transaction_counts():
    # An event that arrived late: another account already used the
    # device after it.
    assert shared_device.evaluate(_context(0, 1, 2, -1), _rule()) is not None


def test_thresholds_come_from_the_catalog():
    ctx = _context(0, 1, 5)

    assert shared_device.evaluate(ctx, _rule(max_accounts=2)) is not None
    assert shared_device.evaluate(ctx, _rule(max_accounts=2, window_days=3)) is None


# record_device, against Valkey.


@pytest.fixture
def device():
    try:
        get_cache().ping()
    except valkey.exceptions.ConnectionError:
        pytest.skip("Valkey is not available at VALKEY_URL")

    device_id = str(uuid4())
    yield device_id
    get_cache().delete(device_key(device_id))


def test_record_device_keeps_each_account_once_with_its_last_time(device):
    record_device(device, "a", BASE)
    record_device(device, "b", BASE + timedelta(days=1))
    uses = record_device(device, "a", BASE + timedelta(days=2))

    assert uses == [
        DeviceUse("b", to_ms(BASE + timedelta(days=1))),
        DeviceUse("a", to_ms(BASE + timedelta(days=2))),
    ]


def test_record_device_drops_accounts_older_than_the_retention(device):
    record_device(device, "old", BASE)
    uses = record_device(device, "new", BASE + timedelta(days=history.DEVICE_DAYS, seconds=1))

    assert [u.account for u in uses] == ["new"]
    assert get_cache().ttl(device_key(device)) > 0


# Through the API: four accounts on one device.


@pytest.fixture
def accounts():
    """Four active accounts, none on the restricted list, with empty
    history."""
    session = get_session()
    try:
        rows = (
            session.query(Cuenta)
            .join(Usuario, Usuario.id == Cuenta.user_id)
            .outerjoin(
                ListaRestrictiva,
                ListaRestrictiva.documento
                == func.regexp_replace(Usuario.documento, r"\D", "", "g"),
            )
            .filter(Cuenta.estado == "activa", ListaRestrictiva.id.is_(None))
            .order_by(Cuenta.id)
            .limit(4)
            .all()
        )
    finally:
        session.close()

    assert len(rows) == 4, "The seed needs 4 active accounts"
    for account in rows:
        get_cache().delete(f"out:{account.id}", f"in:{account.id}")
    return rows


def _money(amount, currency) -> str:
    return str(Decimal(amount).quantize(Decimal(1).scaleb(-MONEDA_DECIMALES[currency])))


def _withdrawal(account, device_id, date) -> dict:
    return {
        "id": str(uuid4()),
        "type": "RETIRO",
        "channel": "CAJERO",
        "source_account_id": str(account.id),
        "amount": _money(1, account.moneda),
        "currency": account.moneda,
        "source_balance_before": _money(1000, account.moneda),
        "source_balance_after": _money(999, account.moneda),
        "device_id": device_id,
        "transaction_date": date.isoformat(),
    }


def test_fourth_account_on_a_device_raises_the_risk_score(accounts, device):
    now = datetime.now(timezone.utc)
    decisions = []
    for i, account in enumerate(accounts):
        response = client.post(
            "/transactions", json=_withdrawal(account, device, now + timedelta(minutes=i))
        )
        assert response.status_code == 200, response.text
        decisions.append(response.json())

    assert [d["risk_score"] for d in decisions] == [0, 0, 0, 30]
    last = decisions[-1]
    assert last["decision"] == "APPROVE"
    assert last["rules_triggered"] == ["shared_device"]
    assert last["opens_case"] is False

    # Any of the four accounts that uses the device again gets it too.
    again = client.post(
        "/transactions", json=_withdrawal(accounts[0], device, now + timedelta(minutes=5))
    ).json()
    assert again["rules_triggered"] == ["shared_device"]
    assert again["risk_score"] == 30
