"""Treasury's reconciliation routes (HU-38 to HU-41, RN-10) against a
schema of their own:

    GET  /reconciliation/differences
    GET  /reconciliation/differences/aging
    POST /reconciliation/differences/{difference_id}/resolution

The differences are inserted by hand; store.py's tests cover how the
reconciliation writes them.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from services.cases_api import routes_reconciliation
from shared.reconciliation import (
    DifferenceStatus,
    ReconciliationDifference,
    ReconciliationRun,
    RunStatus,
)

URL = "/reconciliation/differences"
TODAY = date(2026, 11, 2)
DETECTED = datetime(2026, 11, 2, 7, 4, tzinfo=UTC)
TREASURY = {"X-User": "tesoreria.maria"}


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    """Ages count from run_day to today in UTC: pin today."""
    monkeypatch.setattr(routes_reconciliation, "today", lambda: TODAY)


def _difference(factory, *, days_old=0, partner="cajeros_express", type_="MISSING_IN_PARTNER",
                currency="USD", ours="20.00", theirs=None, status=DifferenceStatus.PENDING,
                reference=None):
    """One difference of the day `days_old` days before TODAY (its run is
    created if missing); returns its id."""
    run_day = TODAY - timedelta(days=days_old)
    ours_amount = None if ours is None else Decimal(ours)
    theirs_amount = None if theirs is None else Decimal(theirs)
    with factory() as session:
        run = session.scalars(select(ReconciliationRun).where(ReconciliationRun.run_day == run_day)).first()
        if run is None:
            run = ReconciliationRun(run_day=run_day, status=RunStatus.DONE.value, started_at=DETECTED)
            session.add(run)
            session.flush()
        difference = ReconciliationDifference(
            run_id=run.id,
            run_day=run_day,
            partner=partner,
            type=type_,
            reference=reference or str(uuid4()),
            partner_reference=None if theirs is None else "CX000000099",
            currency=currency,
            pagoseguro_amount=ours_amount,
            partner_amount=theirs_amount,
            amount_difference=(theirs_amount - ours_amount
                               if type_ == "AMOUNT_MISMATCH" else None),
            pagoseguro_at=None if ours is None else DETECTED - timedelta(days=days_old, hours=6),
            partner_at=None if theirs is None else DETECTED - timedelta(days=days_old, hours=6),
            status=status.value,
            detected_at=DETECTED,
        )
        if status is DifferenceStatus.RESOLVED:
            difference.resolved_at = DETECTED
            difference.resolved_by = "tesoreria"
            difference.resolution_note = "Settled."
        session.add(difference)
        session.commit()
        return difference.id


def _ids(response):
    return [item["id"] for item in response.json()["items"]]


# --- GET /reconciliation/differences (HU-38, HU-39, HU-40) ----------------------

def test_missing_at_the_partner_listed_by_partner_with_amount_and_date(client, sessions):  # HU-38
    andino = _difference(sessions, partner="banco_andino", ours="27.07")
    cajeros = _difference(sessions, partner="cajeros_express", ours="60.00")
    _difference(sessions, type_="MISSING_IN_PAGOSEGURO", ours=None, theirs="5.25")

    response = client.get(URL, params={"type": "MISSING_IN_PARTNER"})

    assert response.status_code == 200
    assert _ids(response) == [str(andino), str(cajeros)]  # same day: by partner
    first = response.json()["items"][0]
    assert (first["partner"], first["pagoseguro_amount"], first["currency"]) == (
        "banco_andino", "27.07", "USD")
    assert first["pagoseguro_at"].startswith("2026-11-02T01:04:00")
    assert (first["partner_amount"], first["partner_at"]) == (None, None)
    assert response.json()["total"] == 2


def test_missing_at_pagoseguro_listed_with_the_partners_amount(client, sessions):  # HU-39
    theirs = _difference(sessions, partner="qr_pagos", type_="MISSING_IN_PAGOSEGURO",
                         ours=None, theirs="5.25")
    _difference(sessions)

    response = client.get(URL, params={"type": "MISSING_IN_PAGOSEGURO", "partner": "qr_pagos"})

    [only] = response.json()["items"]
    assert only["id"] == str(theirs)
    assert (only["partner_amount"], only["partner_reference"], only["pagoseguro_amount"]) == (
        "5.25", "CX000000099", None)
    assert only["partner_at"] is not None


@pytest.mark.parametrize(("currency", "ours", "theirs", "shown"), [
    ("COP", "123456.78", "123457.00", ("123456.78", "123457.00", "0.22")),
    ("USD", "100.00", "99.50", ("100.00", "99.50", "-0.50")),
    ("EUR", "88.91", "89.00", ("88.91", "89.00", "0.09")),
    ("JPY", "1500", "1502", ("1500", "1502", "2")),  # JPY without decimals
])
def test_an_amount_difference_shows_both_amounts(client, sessions, currency, ours, theirs, shown):  # HU-40
    _difference(sessions, type_="AMOUNT_MISMATCH", currency=currency, ours=ours, theirs=theirs)

    [only] = client.get(URL, params={"type": "AMOUNT_MISMATCH"}).json()["items"]

    assert (only["pagoseguro_amount"], only["partner_amount"], only["amount_difference"]) == shown


def test_by_default_only_pending_oldest_day_first(client, sessions):
    recent = _difference(sessions, days_old=1)
    old = _difference(sessions, days_old=9)
    _difference(sessions, days_old=5, status=DifferenceStatus.RESOLVED)

    response = client.get(URL)

    assert _ids(response) == [str(old), str(recent)]
    assert [i["age_days"] for i in response.json()["items"]] == [9, 1]


def test_resolved_ones_on_request_without_age(client, sessions):
    resolved = _difference(sessions, days_old=5, status=DifferenceStatus.RESOLVED)

    [only] = client.get(URL, params={"status": "RESOLVED"}).json()["items"]

    assert only["id"] == str(resolved)
    assert (only["status"], only["age_days"], only["resolved_by"]) == ("RESOLVED", None, "tesoreria")


def test_from_and_to_are_run_days_inclusive(client, sessions):
    _difference(sessions, days_old=10)
    first = _difference(sessions, days_old=7)
    last = _difference(sessions, days_old=3)
    _difference(sessions, days_old=2)

    response = client.get(URL, params={"from": "2026-10-26", "to": "2026-10-30"})

    assert _ids(response) == [str(first), str(last)]


def test_pagination(client, sessions):
    ids = [_difference(sessions, days_old=d) for d in (5, 4, 3, 2, 1)]

    first = client.get(URL, params={"page": 1, "size": 2}).json()
    last = client.get(URL, params={"page": 3, "size": 2}).json()

    assert [i["id"] for i in first["items"]] == [str(ids[0]), str(ids[1])]
    assert (first["total"], first["page"], first["size"]) == (5, 1, 2)
    assert [i["id"] for i in last["items"]] == [str(ids[4])]
    assert client.get(URL, params={"size": 200}).status_code == 200


def test_an_empty_list(client, sessions):
    assert client.get(URL).json() == {"items": [], "total": 0, "page": 1, "size": 50}


def test_invalid_filters_are_400(client, sessions):
    for params in ({"type": "LOST"}, {"partner": "banco_falso"}, {"status": "OPEN"},
                   {"from": "2026-13-01"}, {"size": 201}, {"size": 0}, {"page": 0}):
        response = client.get(URL, params=params)
        assert response.status_code == 400, params
        assert response.json()["detail"] == "The request contains invalid data."

    response = client.get(URL, params={"from": "2026-11-02", "to": "2026-11-01"})
    assert response.status_code == 400
    assert response.json() == {"detail": "`from` must not be after `to`."}


# --- GET /reconciliation/differences/aging (HU-41) ----------------------------

@pytest.mark.parametrize(("days_old", "label"), [
    (0, "0-1"), (1, "0-1"), (2, "2-7"), (7, "2-7"), (8, "8+"), (30, "8+"),
])
def test_each_age_falls_in_its_range(client, sessions, days_old, label):
    _difference(sessions, days_old=days_old)

    body = client.get(f"{URL}/aging").json()

    counts = {r["range"]: r["count"] for r in body["ranges"]}
    assert counts == {"0-1": 0, "2-7": 0, "8+": 0, label: 1}
    assert body["total"] == 1


def test_aging_counts_by_type_and_skips_resolved(client, sessions):
    _difference(sessions, days_old=0)
    _difference(sessions, days_old=1, type_="MISSING_IN_PAGOSEGURO", ours=None, theirs="5.25")
    _difference(sessions, days_old=3, type_="AMOUNT_MISMATCH", ours="10.00", theirs="10.50")
    _difference(sessions, days_old=3)
    _difference(sessions, days_old=12, status=DifferenceStatus.RESOLVED)

    body = client.get(f"{URL}/aging").json()

    assert body["total"] == 4
    assert body["ranges"] == [
        {"range": "0-1", "count": 2, "by_type": {
            "MISSING_IN_PARTNER": 1, "MISSING_IN_PAGOSEGURO": 1, "AMOUNT_MISMATCH": 0}},
        {"range": "2-7", "count": 2, "by_type": {
            "MISSING_IN_PARTNER": 1, "MISSING_IN_PAGOSEGURO": 0, "AMOUNT_MISMATCH": 1}},
        {"range": "8+", "count": 0, "by_type": {
            "MISSING_IN_PARTNER": 0, "MISSING_IN_PAGOSEGURO": 0, "AMOUNT_MISMATCH": 0}},
    ]


def test_aging_by_partner(client, sessions):
    _difference(sessions, partner="qr_pagos", days_old=2)
    _difference(sessions, partner="banco_andino", days_old=2)

    body = client.get(f"{URL}/aging", params={"partner": "qr_pagos"}).json()

    assert body["total"] == 1
    assert client.get(f"{URL}/aging", params={"partner": "nobody"}).status_code == 400


def test_aging_without_differences_has_the_three_ranges(client, sessions):
    body = client.get(f"{URL}/aging").json()

    assert body["total"] == 0
    assert [(r["range"], r["count"]) for r in body["ranges"]] == [("0-1", 0), ("2-7", 0), ("8+", 0)]


# --- POST /reconciliation/differences/{id}/resolution (HU-41) -----------------

def _resolve(client, difference_id, note="Settled in the next file.", headers=TREASURY):
    return client.post(f"{URL}/{difference_id}/resolution", json={"note": note}, headers=headers)


def test_a_resolved_difference_is_no_longer_pending(client, sessions):
    difference_id = _difference(sessions, days_old=3)

    response = _resolve(client, difference_id, note="  Settled in the next file.  ")

    assert response.status_code == 200
    body = response.json()
    assert (body["status"], body["age_days"]) == ("RESOLVED", None)
    assert (body["resolved_by"], body["resolution_note"]) == ("tesoreria.maria", "Settled in the next file.")
    assert body["resolved_at"] is not None
    assert client.get(URL).json()["total"] == 0
    assert client.get(f"{URL}/aging").json()["total"] == 0
    assert _ids(client.get(URL, params={"status": "RESOLVED"})) == [str(difference_id)]


def test_resolving_twice_is_409(client, sessions):
    difference_id = _difference(sessions)
    _resolve(client, difference_id, note="First.")

    response = _resolve(client, difference_id, note="Second.")

    assert response.status_code == 409
    assert response.json() == {"detail": "The difference is resolved; it can no longer change."}
    with sessions() as session:
        assert session.get(ReconciliationDifference, difference_id).resolution_note == "First."


def test_without_x_user_is_400(client, sessions):
    difference_id = _difference(sessions)

    for headers in ({}, {"X-User": "  "}, {"X-User": "x" * 101}):
        response = _resolve(client, difference_id, headers=headers)
        assert response.status_code == 400, headers
        assert response.json() == {"detail": "X-User must have 1 to 100 characters."}

    with sessions() as session:
        assert session.get(ReconciliationDifference, difference_id).status == "PENDING"


def test_an_invalid_note_is_400(client, sessions):
    difference_id = _difference(sessions)

    for body in ({}, {"note": ""}, {"note": "   "}, {"note": "x" * 2001}):
        response = client.post(f"{URL}/{difference_id}/resolution", json=body, headers=TREASURY)
        assert response.status_code == 400, body


def test_an_unknown_difference_is_404(client, sessions):
    response = _resolve(client, uuid4())

    assert response.status_code == 404
    assert response.json() == {"detail": "Difference not found."}


def test_an_id_that_is_not_a_uuid_is_400(client, sessions):
    assert _resolve(client, "not-a-uuid").status_code == 400
