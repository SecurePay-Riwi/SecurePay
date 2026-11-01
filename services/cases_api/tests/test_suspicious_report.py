"""GET /reports/suspicious (HU-35) against a schema of its own.

The compliance cases of a period (RN-03, RN-05, RN-06) with their
account, pattern and amounts in the original currency and in USD
(RN-11), as JSON or as a CSV file.
"""

import csv
import io
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from services.cases_api.schemas import SuspiciousReport
from shared.cases import Case, CaseStatus


def _case(sessions, created_at, *, rules=("mule",), amount="100.00", currency="USD",
          amount_usd="100.00", status=CaseStatus.OPEN, outcome=None):
    """Insert a case opened at created_at; returns its id."""
    tx_id = uuid4()
    case = Case(
        transaction_id=tx_id,
        account_id=uuid4(),
        decision="HOLD",
        decision_reason="Test case.",
        rules_triggered=list(rules),
        rules_version="1",
        amount=Decimal(amount),
        currency=currency,
        amount_usd=None if amount_usd is None else Decimal(amount_usd),
        transaction_date=created_at,
        transaction={"id": str(tx_id)},
        status=status.value,
        outcome=outcome,
        created_at=created_at,
        due_at=created_at + timedelta(hours=4),
    )
    with sessions() as session:
        session.add(case)
        session.commit()
        return case.id


def _at(day, hour=12):
    return datetime(2026, 10, day, hour, tzinfo=UTC)


def _report(client, start="2026-10-10", end="2026-10-20", **params):
    return client.get("/reports/suspicious", params={"from": start, "to": end, **params})


def test_the_cases_of_the_period_with_account_pattern_and_usd(client, sessions):
    mule = _case(sessions, _at(12), rules=("mule",), amount="950000.00", currency="COP",
                 amount_usd="230.05", status=CaseStatus.RESOLVED, outcome="FRAUD")
    split = _case(sessions, _at(11), rules=("splitting", "velocity"), amount="4000.00",
                  currency="EUR", amount_usd="4320.00", status=CaseStatus.ESCALATED)
    listed = _case(sessions, _at(15), rules=("restricted_list",))

    response = _report(client)

    assert response.status_code == 200
    report = SuspiciousReport.model_validate(response.json())
    assert [i.case_id for i in report.items] == [split, mule, listed]  # oldest first
    assert report.total == 3
    assert report.message is None
    assert [i.pattern for i in report.items] == ["splitting+velocity", "mule", "restricted_list"]
    cop = response.json()["items"][1]
    assert (cop["amount"], cop["currency"], cop["amount_usd"]) == ("950000.00", "COP", "230.05")
    assert (cop["status"], cop["outcome"]) == ("RESOLVED", "FRAUD")
    assert response.json()["from"] == "2026-10-10"
    assert response.json()["to"] == "2026-10-20"


def test_both_days_are_inclusive_in_utc(client, sessions):
    first = _case(sessions, datetime(2026, 10, 10, 0, 0, tzinfo=UTC))
    last = _case(sessions, datetime(2026, 10, 20, 23, 59, 59, tzinfo=UTC))
    _case(sessions, datetime(2026, 10, 9, 23, 59, 59, tzinfo=UTC))
    _case(sessions, datetime(2026, 10, 21, 0, 0, tzinfo=UTC))

    items = _report(client).json()["items"]

    assert [i["case_id"] for i in items] == [str(first), str(last)]


def test_a_period_without_cases_is_empty_and_says_so(client, sessions):
    _case(sessions, _at(5))

    response = _report(client)

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["total"] == 0
    assert response.json()["message"] == "No compliance cases in the period."


def test_one_day_period(client, sessions):
    case_id = _case(sessions, _at(14, hour=3))

    items = _report(client, "2026-10-14", "2026-10-14").json()["items"]

    assert [i["case_id"] for i in items] == [str(case_id)]


def test_the_csv_export(client, sessions):
    _case(sessions, _at(12), rules=("mule",), amount="950000.00", currency="COP",
          amount_usd="230.05", status=CaseStatus.RESOLVED, outcome="FRAUD")
    _case(sessions, _at(13), rules=("splitting",), amount="12345678.90", currency="JPY",
          amount_usd=None)

    response = _report(client, format="csv")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"] == (
        'attachment; filename="suspicious-report-2026-10-10-2026-10-20.csv"')
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert list(rows[0]) == ["case_id", "transaction_id", "account_id", "pattern", "amount",
                             "currency", "amount_usd", "status", "outcome", "created_at"]
    assert [(r["pattern"], r["amount"], r["currency"], r["amount_usd"], r["status"], r["outcome"])
            for r in rows] == [
        ("mule", "950000.00", "COP", "230.05", "RESOLVED", "FRAUD"),
        ("splitting", "12345678.90", "JPY", "", "OPEN", ""),  # no scientific notation
    ]
    assert rows[0]["created_at"] == "2026-10-12T12:00:00+00:00"


def test_an_empty_csv_has_only_the_header(client, sessions):
    response = _report(client, format="csv")

    assert response.status_code == 200
    assert response.text == (
        "case_id,transaction_id,account_id,pattern,amount,currency,"
        "amount_usd,status,outcome,created_at\n"
    )


def test_from_after_to_is_400(client, sessions):
    response = _report(client, "2026-10-20", "2026-10-10")

    assert response.status_code == 400
    assert response.json() == {"detail": "`from` must not be after `to`."}


def test_more_than_31_days_is_400(client, sessions):
    assert _report(client, "2026-10-01", "2026-10-31").status_code == 200  # 31 days
    response = _report(client, "2026-10-01", "2026-11-01")  # 32 days

    assert response.status_code == 400
    assert response.json() == {"detail": "The period can have at most 31 days."}


def test_invalid_input_is_400(client, sessions):
    for params in ({"to": "2026-10-20"}, {"from": "2026-10-10"},
                   {"from": "2026-13-01", "to": "2026-10-20"},
                   {"from": "yesterday", "to": "2026-10-20"},
                   {"from": "2026-10-10", "to": "2026-10-20", "format": "pdf"}):
        response = client.get("/reports/suspicious", params=params)
        assert response.status_code == 400, params
        assert response.json()["detail"] == "The request contains invalid data."
