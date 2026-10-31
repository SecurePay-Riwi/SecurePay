"""GET /accounts/{account_id}/related-accounts (HU-29) against a schema of its own.

The network is seeded in each test: account A uses a device shared by 5
accounts, and one of them also uses a second device.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from services.cases_api import deps
from shared.cases import AccountTransaction, Case, CaseStatus


def _url(account, **params):
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"/accounts/{account}/related-accounts" + (f"?{query}" if query else "")


def _use(factory, account, device, days_ago=1.0, direction="OUT"):
    """One account_transactions row: the account used the device."""
    when = datetime.now(UTC) - timedelta(days=days_ago)
    with factory() as session:
        session.add(AccountTransaction(
            transaction_id=uuid4(),
            account_id=account,
            direction=direction,
            counterparty_account_id=None,
            type="RETIRO",
            channel="APP",
            amount=Decimal("10.00"),
            currency="USD",
            amount_usd=Decimal("10.00"),
            device_id=device,
            decision="APPROVE",
            decision_reason="Below USD 50.",
            rules_triggered=[],
            risk_score=0,
            transaction_date=when,
            processed_at=when,
        ))
        session.commit()
    return when


def _case(factory, account, status=CaseStatus.OPEN):
    now = datetime.now(UTC)
    with factory() as session:
        session.add(Case(
            transaction_id=uuid4(),
            account_id=account,
            decision="HOLD",
            decision_reason="Mule account.",
            rules_triggered=["mule"],
            rules_version="1",
            amount=Decimal("10.00"),
            currency="USD",
            amount_usd=Decimal("10.00"),
            transaction_date=now,
            transaction={},
            status=status.value,
            created_at=now,
            due_at=now + timedelta(hours=4),
        ))
        session.commit()


def test_the_accounts_on_the_same_devices(client, sessions):
    a, b, c, d, e = (uuid4() for _ in range(5))
    shared, other = uuid4(), uuid4()
    for days_ago, account in enumerate([a, b, c, d, e], start=1):
        _use(sessions, account, shared, days_ago)
    _use(sessions, b, other, 0.5)  # B's second device: A never used it
    _use(sessions, uuid4(), other, 0.5)  # nobody of A's network
    _case(sessions, c)
    _case(sessions, c, CaseStatus.ESCALATED)
    _case(sessions, d, CaseStatus.RESOLVED)

    response = client.get(_url(a))

    assert response.status_code == 200
    body = response.json()
    assert body["account_id"] == str(a) and body["days"] == 30
    # The latest seen first; A itself is not listed; B only by the shared device.
    assert [i["account_id"] for i in body["items"]] == [str(b), str(c), str(d), str(e)]
    assert {i["device_id"] for i in body["items"]} == {str(shared)}
    assert body["total"] == 4
    open_cases = {i["account_id"]: i["open_cases"] for i in body["items"]}
    assert open_cases == {str(b): 0, str(c): 2, str(d): 0, str(e): 0}
    assert set(body["items"][0]) == {"account_id", "device_id", "last_seen", "open_cases"}


def test_one_item_per_shared_device_with_its_last_use(client, sessions):
    a, b = uuid4(), uuid4()
    phone, laptop = uuid4(), uuid4()
    _use(sessions, a, phone)
    _use(sessions, a, laptop)
    _use(sessions, b, phone, 3)
    last = _use(sessions, b, phone, 2)
    _use(sessions, b, laptop, 5)

    items = client.get(_url(a)).json()["items"]

    assert [(i["account_id"], i["device_id"]) for i in items] == [
        (str(b), str(phone)), (str(b), str(laptop)),
    ]
    assert datetime.fromisoformat(items[0]["last_seen"]) == last


def test_a_use_of_31_days_ago_does_not_count(client, sessions):
    a, b, c = uuid4(), uuid4(), uuid4()
    device, old_device = uuid4(), uuid4()
    _use(sessions, a, device)
    _use(sessions, b, device, 31)  # B used it, but too long ago
    _use(sessions, c, device, 29)
    _use(sessions, a, old_device, 31)  # A's old device does not count
    _use(sessions, b, old_device, 1)

    assert [i["account_id"] for i in client.get(_url(a)).json()["items"]] == [str(c)]
    assert client.get(_url(a, days=7)).json()["items"] == []


def test_the_received_side_has_no_device(client, sessions):
    a, b = uuid4(), uuid4()
    device = uuid4()
    _use(sessions, a, device)
    # B's IN row of the same transaction carries no device (HU-28).
    _use(sessions, b, None, direction="IN")

    assert client.get(_url(a)).json()["items"] == []


def test_an_account_without_devices_is_an_empty_list(client, sessions):
    response = client.get(_url(uuid4()))

    assert response.status_code == 200
    assert response.json()["items"] == [] and response.json()["total"] == 0


def test_invalid_input_is_400(client, sessions):
    assert client.get("/accounts/not-a-uuid/related-accounts").status_code == 400
    for days in (0, 31):
        assert client.get(_url(uuid4(), days=days)).status_code == 400


def test_without_postgresql_is_503(client):
    deps.bind(sessionmaker(bind=create_engine("postgresql+psycopg://x:x@127.0.0.1:1/x")))

    assert client.get(_url(uuid4())).status_code == 503
