"""RN-07 / HU-17 end to end: security events through POST
/security-events, then a withdrawal through POST /transactions.

Needs the seed loaded in PostgreSQL and Valkey.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func

from services.decision_engine.currency import RATES_PER_USD
from services.decision_engine.main import app
from services.decision_engine.security_events import security_key
from shared.cache import get_cache
from shared.config import MONEDA_DECIMALES
from shared.db import get_session
from shared.models import Cuenta, DispositivoCuenta, ListaRestrictiva, Usuario

client = TestClient(app)


@pytest.fixture
def account():
    """An active account not on the restricted list, with empty history."""
    session = get_session()
    try:
        row = (
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
            .first()
        )
    finally:
        session.close()

    assert row is not None, "The seed needs an active account"
    acc, device = row
    keys = (f"out:{acc.id}", f"in:{acc.id}", security_key(acc.id))
    get_cache().delete(*keys)
    yield acc, device
    get_cache().delete(*keys)


def _money(usd, currency) -> str:
    amount = Decimal(usd) * RATES_PER_USD[currency]
    return str(amount.quantize(Decimal(1).scaleb(-MONEDA_DECIMALES[currency])))


def _security_event(acc, type_, date):
    response = client.post(
        "/security-events",
        json={
            "id": str(uuid4()),
            "type": type_,
            "user_id": str(acc.user_id),
            "account_id": str(acc.id),
            "device_id": str(uuid4()),
            "event_date": date.isoformat(),
        },
    )
    assert response.status_code == 202, response.text


def _withdraw(acc, device, usd, date) -> dict:
    amount = _money(usd, acc.moneda)
    balance = _money(10000, acc.moneda)
    response = client.post(
        "/transactions",
        json={
            "id": str(uuid4()),
            "type": "RETIRO",
            "channel": "CAJERO",
            "source_account_id": str(acc.id),
            "amount": amount,
            "currency": acc.moneda,
            "source_balance_before": balance,
            "source_balance_after": str(Decimal(balance) - Decimal(amount)),
            "device_id": str(device),
            "transaction_date": date.isoformat(),
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_generator_pattern_is_held(account):
    # The generator's pattern: device change, password change 5 minutes
    # later, withdrawal 20 minutes after the device change.
    acc, device = account
    base = datetime.now(UTC)
    _security_event(acc, "DEVICE_CHANGE", base)
    _security_event(acc, "PASSWORD_CHANGE", base + timedelta(minutes=5))

    decision = _withdraw(acc, device, 300, base + timedelta(minutes=20))

    assert decision["decision"] == "HOLD"
    assert decision["rules_triggered"] == ["account_takeover"]
    assert decision["decision_reason"].startswith("Account takeover:")


def test_generator_control_is_approved(account):
    # The control: the withdrawal comes 70 minutes after the device change.
    acc, device = account
    base = datetime.now(UTC)
    _security_event(acc, "DEVICE_CHANGE", base)
    _security_event(acc, "PASSWORD_CHANGE", base + timedelta(minutes=5))

    decision = _withdraw(acc, device, 300, base + timedelta(minutes=70))

    assert decision["decision"] == "APPROVE"
    assert "account_takeover" not in decision["rules_triggered"]


def test_small_withdrawal_after_both_changes_is_approved(account):
    acc, device = account
    base = datetime.now(UTC)
    _security_event(acc, "DEVICE_CHANGE", base)
    _security_event(acc, "PASSWORD_CHANGE", base + timedelta(minutes=5))

    decision = _withdraw(acc, device, 150, base + timedelta(minutes=20))

    assert decision["decision"] == "APPROVE"
