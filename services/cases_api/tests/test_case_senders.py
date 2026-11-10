"""GET /cases/{case_id}/senders (CA-02) against a schema of its own: the
mule network of a case, from the IN rows of the account history."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from shared.cases import AccountTransaction, Case, CaseStatus


def _received(factory, account, sender, when, usd="50.00", type_="P2P"):
    """One IN row: `sender` sent a transfer to `account` at `when`."""
    with factory() as session:
        session.add(
            AccountTransaction(
                transaction_id=uuid4(),
                account_id=account,
                direction="IN",
                counterparty_account_id=sender,
                type=type_,
                channel="APP",
                amount=Decimal(usd),
                currency="USD",
                amount_usd=Decimal(usd),
                decision="APPROVE",
                decision_reason="Below USD 50.",
                rules_triggered=[],
                risk_score=0,
                transaction_date=when,
                processed_at=when,
            )
        )
        session.commit()


def _case(factory, account, when, usd="180.00", status=CaseStatus.OPEN):
    case_id = uuid4()
    with factory() as session:
        session.add(
            Case(
                id=case_id,
                transaction_id=uuid4(),
                account_id=account,
                decision="HOLD",
                decision_reason="Mule account.",
                rules_triggered=["mule"],
                rules_version="1",
                amount=Decimal(usd),
                currency="USD",
                amount_usd=Decimal(usd),
                transaction_date=when,
                transaction={},
                status=status.value,
                created_at=when,
                due_at=when + timedelta(hours=4),
            )
        )
        session.commit()
    return case_id


def test_the_senders_of_a_mule_case(client, sessions):
    mule, a, b, c = (uuid4() for _ in range(4))
    withdrawal = datetime(2026, 10, 31, 14, 0, tzinfo=UTC)
    _received(sessions, mule, a, withdrawal - timedelta(minutes=25), "40.00")
    _received(sessions, mule, a, withdrawal - timedelta(minutes=10), "60.00")
    _received(sessions, mule, b, withdrawal - timedelta(minutes=15), "50.00")
    _received(sessions, mule, c, withdrawal - timedelta(minutes=5), "50.00")
    _received(sessions, mule, uuid4(), withdrawal - timedelta(minutes=45))  # too early
    _received(sessions, mule, uuid4(), withdrawal + timedelta(minutes=1))  # after it
    _received(
        sessions, uuid4(), a, withdrawal - timedelta(minutes=5)
    )  # another account
    _case(sessions, b, withdrawal)  # B has a case of its own
    case_id = _case(sessions, mule, withdrawal, "180.00")

    response = client.get(f"/cases/{case_id}/senders")

    assert response.status_code == 200
    body = response.json()
    assert body["minutes"] == 30
    assert body["total_senders"] == 3
    assert [s["account_id"] for s in body["senders"]] == [str(a), str(b), str(c)]
    first = body["senders"][0]
    assert first["transfers"] == 2 and Decimal(first["amount_usd"]) == Decimal("100")
    assert [s["open_cases"] for s in body["senders"]] == [0, 1, 0]
    assert Decimal(body["received_usd"]) == Decimal("200")
    assert body["case_vs_received_pct"] == "90.00"


def test_the_window_can_be_wider(client, sessions):
    mule, early = uuid4(), uuid4()
    withdrawal = datetime(2026, 10, 31, 14, 0, tzinfo=UTC)
    _received(sessions, mule, early, withdrawal - timedelta(minutes=45))
    case_id = _case(sessions, mule, withdrawal)

    assert client.get(f"/cases/{case_id}/senders").json()["total_senders"] == 0
    wide = client.get(f"/cases/{case_id}/senders?minutes=60").json()
    assert [s["account_id"] for s in wide["senders"]] == [str(early)]


def test_only_p2p_transfers_count(client, sessions):
    mule = uuid4()
    withdrawal = datetime(2026, 10, 31, 14, 0, tzinfo=UTC)
    _received(
        sessions, mule, uuid4(), withdrawal - timedelta(minutes=5), type_="RECARGA"
    )
    case_id = _case(sessions, mule, withdrawal)

    body = client.get(f"/cases/{case_id}/senders").json()
    assert body["senders"] == [] and body["case_vs_received_pct"] is None


def test_a_missing_case_or_a_bad_window(client):
    assert client.get(f"/cases/{uuid4()}/senders").status_code == 404
    assert client.get(f"/cases/{uuid4()}/senders?minutes=0").status_code == 400
    assert client.get("/cases/not-a-uuid/senders").status_code == 400
