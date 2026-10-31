"""GET /compliance/restricted-list-reports (HU-34) against a schema of its own."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from services.cases_api import deps
from shared.cases import Case, ComplianceReport

URL = "/compliance/restricted-list-reports"
T0 = datetime(2026, 10, 31, 14, 0, tzinfo=UTC)


def _report(factory, matched_at, document="1000000070", list_type="PEP", notified_at=None):
    with factory() as session:
        case = Case(
            transaction_id=uuid4(),
            account_id=uuid4(),
            decision="REJECT",
            decision_reason="Account owner is on a restricted list.",
            rules_triggered=["restricted_list"],
            rules_version="3",
            amount=Decimal("10.00"),
            currency="USD",
            transaction_date=matched_at,
            transaction={},
            created_at=matched_at,
            due_at=matched_at + timedelta(hours=4),
        )
        session.add(case)
        session.flush()
        report = ComplianceReport(
            case_id=case.id,
            transaction_id=case.transaction_id,
            account_id=case.account_id,
            document=document,
            list_type=list_type,
            matched_at=matched_at,
            notified_at=notified_at,
        )
        session.add(report)
        session.commit()
        return str(report.id)


def test_newest_first_with_every_field(client, sessions):
    older = _report(sessions, T0, notified_at=T0 + timedelta(minutes=5))
    newer = _report(sessions, T0 + timedelta(minutes=1), document="1000000016",
                    list_type="sanciones")

    response = client.get(URL)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2 and body["page"] == 1 and body["size"] == 50
    assert [r["id"] for r in body["items"]] == [newer, older]
    first = body["items"][0]
    assert first["document"] == "1000000016"
    assert first["list_type"] == "sanciones"
    assert first["notified_at"] is None
    assert set(first) == {"id", "case_id", "transaction_id", "account_id", "document",
                          "list_type", "matched_at", "notified_at"}
    assert body["items"][1]["notified_at"] is not None


def test_from_is_inclusive_and_to_exclusive(client, sessions):
    _report(sessions, T0 - timedelta(seconds=1))
    inside = _report(sessions, T0)
    _report(sessions, T0 + timedelta(hours=1))

    response = client.get(URL, params={"from": T0.isoformat(),
                                       "to": (T0 + timedelta(hours=1)).isoformat()})

    assert [r["id"] for r in response.json()["items"]] == [inside]


def test_a_date_without_time_zone_is_utc(client, sessions):
    inside = _report(sessions, T0)
    _report(sessions, T0 + timedelta(days=1))

    response = client.get(URL, params={"from": "2026-10-31", "to": "2026-11-01"})

    assert response.status_code == 200
    assert [r["id"] for r in response.json()["items"]] == [inside]


def test_a_period_without_reports_is_an_empty_list(client, sessions):
    _report(sessions, T0)

    response = client.get(URL, params={"from": "2026-01-01", "to": "2026-02-01"})

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "page": 1, "size": 50}


def test_pages(client, sessions):
    ids = [_report(sessions, T0 + timedelta(minutes=i), document=f"10000000{i:02d}")
           for i in range(3)]

    response = client.get(URL, params={"page": 2, "size": 2})

    body = response.json()
    assert body["total"] == 3
    assert [r["id"] for r in body["items"]] == [ids[0]]


def test_from_after_to_is_400(client):
    response = client.get(URL, params={"from": "2026-11-01", "to": "2026-10-01"})

    assert response.status_code == 400
    assert response.json() == {"detail": "`from` must not be after `to`."}


def test_invalid_input_is_400(client):
    for params in ({"from": "yesterday"}, {"size": 101}, {"page": 0}):
        response = client.get(URL, params=params)
        assert response.status_code == 400, params
        assert response.json()["detail"] == "The request contains invalid data."


def test_without_postgresql_is_503(client):
    deps.bind(sessionmaker(bind=create_engine("postgresql+psycopg://x:x@127.0.0.1:1/x")))

    response = client.get(URL)

    assert response.status_code == 503
