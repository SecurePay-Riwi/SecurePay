"""GET /accounts/{account_id}/transactions (HU-28) against a schema of its own."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from shared.cases import AccountTransaction

ACCOUNT = uuid4()


def _url(account=ACCOUNT):
    return f"/accounts/{account}/transactions"


def _row(factory, days_ago, account=ACCOUNT, direction="OUT", **fields):
    when = datetime.now(UTC) - timedelta(days=days_ago)
    values = {
        "transaction_id": uuid4(),
        "account_id": account,
        "direction": direction,
        "counterparty_account_id": uuid4(),
        "type": "P2P",
        "channel": "APP",
        "amount": Decimal("950000.00"),
        "currency": "COP",
        "amount_usd": Decimal("230.05"),
        "device_id": uuid4() if direction == "OUT" else None,
        "decision": "APPROVE",
        "decision_reason": "Below USD 50.",
        "rules_triggered": [],
        "risk_score": 0,
        "transaction_date": when,
        "processed_at": when,
    }
    values.update(fields)
    with factory() as session:
        session.add(AccountTransaction(**values))
        session.commit()
    return str(values["transaction_id"])


def test_newest_first_with_every_field(client, sessions):
    older = _row(sessions, 3)
    newer = _row(sessions, 1, direction="IN", decision="HOLD",
                 rules_triggered=["velocity"], risk_score=40)
    _row(sessions, 1, account=uuid4())  # another account

    response = client.get(_url())

    assert response.status_code == 200
    body = response.json()
    assert body["account_id"] == str(ACCOUNT)
    assert body["days"] == 30
    assert body["total"] == 2 and body["page"] == 1 and body["size"] == 50
    assert [r["transaction_id"] for r in body["items"]] == [newer, older]
    first = body["items"][0]
    assert first["direction"] == "IN" and first["device_id"] is None
    assert first["decision"] == "HOLD" and first["rules_triggered"] == ["velocity"]
    # Money as decimal strings, the original currency and USD.
    assert first["amount"] == "950000.00" and first["currency"] == "COP"
    assert first["amount_usd"] == "230.05"
    assert set(first) == {
        "transaction_id", "direction", "counterparty_account_id", "type", "channel",
        "merchant_id", "amount", "currency", "amount_usd", "device_id", "decision",
        "decision_reason", "rules_triggered", "risk_score", "transaction_date",
        "processed_at",
    }
    assert body["items"][1]["device_id"] is not None


def test_an_account_without_history_is_an_empty_list(client, sessions):
    response = client.get(_url(uuid4()))

    assert response.status_code == 200
    assert response.json()["items"] == [] and response.json()["total"] == 0


def test_a_row_of_31_days_ago_is_not_listed(client, sessions):
    inside = _row(sessions, 29)
    _row(sessions, 31)

    body = client.get(_url()).json()

    assert [r["transaction_id"] for r in body["items"]] == [inside]


def test_days_narrows_the_window(client, sessions):
    recent = _row(sessions, 0.5)
    _row(sessions, 3)

    body = client.get(_url(), params={"days": 1}).json()

    assert body["days"] == 1
    assert [r["transaction_id"] for r in body["items"]] == [recent]


def test_pages(client, sessions):
    ids = [_row(sessions, days) for days in (1, 2, 3)]

    body = client.get(_url(), params={"page": 2, "size": 2}).json()

    assert body["total"] == 3
    assert [r["transaction_id"] for r in body["items"]] == [ids[2]]


def test_invalid_input_is_400(client, sessions):
    for url, params in [
        ("/accounts/not-a-uuid/transactions", {}),
        (_url(), {"days": 0}),
        (_url(), {"days": 31}),
        (_url(), {"page": 0}),
        (_url(), {"size": 101}),
    ]:
        response = client.get(url, params=params)
        assert response.status_code == 400, (url, params)
        assert response.json()["detail"] == "The request contains invalid data."
