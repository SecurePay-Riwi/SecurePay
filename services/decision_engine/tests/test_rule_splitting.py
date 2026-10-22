"""HU-15 / RN-05: splitting. 3 or more transactions from the same
account in 24 hours, each below the daily limit (USD 10000), that
together go over it, open a compliance case.

The unit tests build RuleContext and RuleEntry by hand. The last one
needs the seed in PostgreSQL and Valkey (the API).
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func

from services.decision_engine.currency import RATES_PER_USD, to_usd
from services.decision_engine.history import Outgoing, to_ms
from services.decision_engine.main import app
from services.decision_engine.rules import splitting
from services.decision_engine.rules.base import RuleContext
from services.decision_engine.schemas import Decision, TransactionRequest
from shared.cache import get_cache
from shared.config import MONEDA_DECIMALES
from shared.db import get_session
from shared.models import Cuenta, ListaRestrictiva, Usuario
from shared.rule_catalog import default_catalog

BASE = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)

client = TestClient(app)


def _rule(**params):
    entry = default_catalog().get("splitting")
    return entry.model_copy(update={"params": {**entry.params, **params}})


def _money(amount_usd, currency) -> str:
    amount = Decimal(str(amount_usd)) * RATES_PER_USD[currency]
    return str(amount.quantize(Decimal(1).scaleb(-MONEDA_DECIMALES[currency])))


def _context(*movements, currency="USD") -> RuleContext:
    """The last of `movements` is the transaction being decided. Each one
    is (amount in USD, hours before it)."""
    payload = TransactionRequest(
        id=uuid4(), type="RETIRO", channel="CAJERO",
        source_account_id=uuid4(),
        amount=_money(movements[-1][0], currency), currency=currency,
        source_balance_before=_money(50_000, currency),
        source_balance_after=_money(40_000, currency),
        device_id=uuid4(), transaction_date=BASE,
    )
    outgoing = [
        Outgoing(str(uuid4()), "RETIRO", _money(usd, currency),
                 to_ms(BASE - timedelta(hours=h)))
        for usd, h in movements[:-1]
    ]
    outgoing.append(Outgoing(str(payload.id), "RETIRO", str(payload.amount), to_ms(BASE)))
    outgoing.sort(key=lambda o: o.t)
    return RuleContext(
        payload=payload,
        session=None,
        t_ms=to_ms(BASE),
        amount_usd=to_usd(payload.amount, currency),
        outgoing=outgoing,
    )


def test_two_transactions_do_not_fire():
    assert splitting.evaluate(_context((6000, 5), (6000, 0)), _rule()) is None


def test_three_adding_up_to_exactly_the_limit_do_not_fire():
    ctx = _context((4000, 7), (3000, 3), (3000, 0))
    assert splitting.evaluate(ctx, _rule()) is None


def test_three_going_over_the_limit_open_a_case():
    result = splitting.evaluate(_context((4000, 7), (4000, 3), (4450, 0)), _rule())

    assert result.rule == "splitting"
    assert result.decision == Decision.APPROVE
    assert result.opens_case is True
    assert result.score == 40
    assert result.reason == (
        "Splitting: 3 transactions in 24 hours, each below USD 10000, "
        "adding up to USD 12450.00."
    )


def test_a_transaction_at_the_limit_is_not_part_of_a_split():
    ctx = _context((10000, 7), (4000, 3), (4000, 0))
    assert splitting.evaluate(ctx, _rule()) is None


def test_the_transaction_decided_at_the_limit_does_not_fire():
    ctx = _context((4000, 7), (4000, 5), (4000, 3), (10000, 0))
    assert splitting.evaluate(ctx, _rule()) is None


def test_a_transaction_25_hours_before_is_outside_the_window():
    ctx = _context((4000, 25), (4000, 3), (4000, 0))
    assert splitting.evaluate(ctx, _rule()) is None


def test_a_transaction_recorded_after_the_one_decided_does_not_count():
    ctx = _context((4000, 7), (4000, -1), (4000, 0))
    assert splitting.evaluate(ctx, _rule()) is None


@pytest.mark.parametrize("currency", ["COP", "JPY", "EUR"])
def test_amounts_are_compared_in_usd(currency):
    over = _context((3400, 7), (3400, 3), (3400, 0), currency=currency)
    under = _context((3300, 7), (3300, 3), (3300, 0), currency=currency)

    assert splitting.evaluate(over, _rule()) is not None
    assert splitting.evaluate(under, _rule()) is None


def test_thresholds_come_from_the_catalog():
    ctx = _context((3000, 5), (3000, 0))

    assert splitting.evaluate(ctx, _rule()) is None
    assert splitting.evaluate(ctx, _rule(min_transactions=2, daily_limit_usd="5000")) is not None
    assert splitting.evaluate(ctx, _rule(min_transactions=2, daily_limit_usd="5000",
                                         window_hours=4)) is None


# Through the API: the generator's pattern.


@pytest.fixture
def account():
    """An active account, not on the restricted list, with empty
    history."""
    session = get_session()
    try:
        found = (
            session.query(Cuenta)
            .join(Usuario, Usuario.id == Cuenta.user_id)
            .outerjoin(
                ListaRestrictiva,
                ListaRestrictiva.documento
                == func.regexp_replace(Usuario.documento, r"\D", "", "g"),
            )
            .filter(Cuenta.estado == "activa", ListaRestrictiva.id.is_(None))
            .order_by(Cuenta.id.desc())
            .first()
        )
    finally:
        session.close()

    assert found is not None, "The seed needs an active account"
    get_cache().delete(f"out:{found.id}", f"in:{found.id}")
    return found


def _withdrawal(account, amount_usd, date) -> dict:
    return {
        "id": str(uuid4()),
        "type": "RETIRO",
        "channel": "CAJERO",
        "source_account_id": str(account.id),
        "amount": _money(amount_usd, account.moneda),
        "currency": account.moneda,
        "source_balance_before": _money(20_000, account.moneda),
        "source_balance_after": _money(20_000 - amount_usd, account.moneda),
        "device_id": str(uuid4()),
        "transaction_date": date.isoformat(),
    }


def test_three_withdrawals_over_the_limit_are_approved_with_a_case(account, eventos_publicados):
    # The generator's pattern: USD 3400 to 3900 at hours 0, 3 and 7.
    base = datetime.now(timezone.utc)
    decisions = []
    for amount, hours in ((3500, 0), (3600, 3), (3700, 7)):
        response = client.post(
            "/transactions", json=_withdrawal(account, amount, base + timedelta(hours=hours))
        )
        assert response.status_code == 200, response.text
        decisions.append(response.json())

    assert [d["opens_case"] for d in decisions] == [False, False, True]
    last = decisions[-1]
    assert last["decision"] == "APPROVE"
    assert last["rules_triggered"] == ["splitting"]
    assert last["risk_score"] == 40
    assert last["decision_reason"].startswith("Splitting: 3 transactions in 24 hours")
    assert eventos_publicados[-1]["decision"]["opens_case"] is True
