"""The reconciliation contract of shared/reconciliation.py (Sprint 5).

The table tests need PostgreSQL (DATABASE_URL); they run in a schema of
their own.
"""

import uuid
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from shared.reconciliation import (
    AGE_RANGES,
    DifferenceStatus,
    MatchRow,
    MatchStatus,
    Partner,
    ReconciliationDifference,
    ReconciliationRun,
    RejectedRow,
    RunStatus,
    StatementRecord,
    create_schema,
    match_row_from_json,
    partner_day,
    partner_for,
    record_from_json,
    to_json,
)
from shared.tests.isolated_db import isolated_sessions


@pytest.mark.parametrize(
    ("tx_type", "channel", "partner"),
    [
        ("RECARGA", "APP", Partner.BANCO_ANDINO),
        ("RECARGA", "WEB", Partner.BANCO_ANDINO),
        ("RECARGA", "CORRESPONSAL", Partner.RED_CORRESPONSALES),
        ("RETIRO", "CORRESPONSAL", Partner.RED_CORRESPONSALES),
        ("RETIRO", "CAJERO", Partner.CAJEROS_EXPRESS),
        ("QR", "APP", Partner.QR_PAGOS),
        ("P2P", "APP", None),
        ("P2P", "WEB", None),
    ],
)
def test_partner_for(tx_type, channel, partner):
    assert partner_for(tx_type, channel) == partner


def test_partner_day_uses_the_partner_time_zone():
    # 23:30 in Bogota on the 5th is 04:30 UTC on the 6th.
    at = datetime(2026, 10, 6, 4, 30, tzinfo=UTC)
    assert partner_day(Partner.RED_CORRESPONSALES, at) == date(2026, 10, 5)
    assert partner_day("cajeros_express", at) == date(2026, 10, 5)
    assert partner_day(Partner.BANCO_ANDINO, at) == date(2026, 10, 6)
    assert partner_day("qr_pagos", at) == date(2026, 10, 6)


def test_partner_day_needs_a_time_zone():
    with pytest.raises(ValueError):
        partner_day(Partner.QR_PAGOS, datetime(2026, 10, 5, 12, 0))


def test_age_ranges_cover_every_day():
    assert [label for label, *_ in AGE_RANGES] == ["0-1", "2-7", "8+"]
    for (_, _, high), (_, low, _) in zip(AGE_RANGES, AGE_RANGES[1:], strict=False):
        assert low == high + 1
    assert AGE_RANGES[-1][2] is None


RECORD = StatementRecord(
    partner="banco_andino",
    statement_day=date(2026, 10, 5),
    file_name="banco_andino_20261005_v2.csv",
    line_number=4,
    pagoseguro_reference="5fe95c21-6adb-57d9-bcd6-92d958c69913",
    partner_reference="BA000000003",
    tx_type="RECARGA",
    currency="EUR",
    amount=Decimal("88.91"),
    # Bogota time, as a reader may build it: written back in UTC.
    transaction_at=datetime(
        2026, 10, 5, 2, 45, 29, tzinfo=timezone(timedelta(hours=-5))
    ),
)


def test_record_json_round_trip():
    data = to_json(RECORD)
    assert data["amount"] == "88.91"
    assert data["statement_day"] == "2026-10-05"
    assert data["transaction_at"] == "2026-10-05T07:45:29+00:00"
    assert record_from_json(data) == RECORD


def test_match_row_json_round_trip_with_nulls():
    row = MatchRow(
        run_day=date(2026, 10, 5),
        partner="qr_pagos",
        status=MatchStatus.ONLY_PARTNER.value,
        reference="99fdc9ad-1c98-59b6-9071-ca21c0864b2f",
        partner_reference="QR000000003",
        currency="JPY",
        pagoseguro_amount=None,
        partner_amount=Decimal("1500"),
        pagoseguro_at=None,
        partner_at=datetime(2026, 10, 5, 14, 30, tzinfo=UTC),
    )
    data = to_json(row)
    assert data["pagoseguro_amount"] is None and data["partner_amount"] == "1500"
    assert match_row_from_json(data) == row


def test_rejected_row_to_json():
    row = RejectedRow(
        "cajeros_express",
        "cajeros_express_20261005_v1.csv",
        4,
        "a;b",
        "amount is not a number",
    )
    assert to_json(row)["reason"] == "amount is not a number"


def test_from_json_refuses_missing_keys_and_naive_times():
    data = to_json(RECORD)
    with pytest.raises(ValueError):
        record_from_json({k: v for k, v in data.items() if k != "amount"})
    with pytest.raises(ValueError):
        record_from_json({**data, "transaction_at": "2026-10-05T07:45:29"})


def test_match_row_from_json_refuses_an_unknown_status():
    data = to_json(
        MatchRow(
            date(2026, 10, 5),
            "qr_pagos",
            "MATCHED",
            "r",
            None,
            "USD",
            None,
            None,
            None,
            None,
        )
    )
    with pytest.raises(ValueError):
        match_row_from_json({**data, "status": "MAYBE"})


def test_times_without_zone_are_refused_on_write():
    with pytest.raises(ValueError):
        to_json(
            MatchRow(
                date(2026, 10, 5),
                "qr_pagos",
                "MATCHED",
                "r",
                None,
                "USD",
                None,
                None,
                datetime(2026, 10, 5),
                None,
            )
        )


# --- Tables ----------------------------------------------------------------


@pytest.fixture
def Session():
    with isolated_sessions("reconciliation_contract_test") as factory:
        with factory() as session:
            create_schema(session)
        yield factory


def _run(session) -> ReconciliationRun:
    run = ReconciliationRun(run_day=date(2026, 10, 5), started_at=datetime.now(UTC))
    session.add(run)
    session.flush()
    return run


def _difference(run, **kw) -> ReconciliationDifference:
    values = dict(
        run_id=run.id,
        run_day=run.run_day,
        partner="qr_pagos",
        type="MISSING_IN_PAGOSEGURO",
        reference="ref-1",
        currency="USD",
        partner_amount=Decimal("5.25"),
        detected_at=datetime.now(UTC),
    )
    return ReconciliationDifference(**{**values, **kw})


def test_create_schema_is_idempotent(Session):
    with Session() as session:
        create_schema(session)
        tables = set(inspect(session.connection()).get_table_names())
    assert tables == {"reconciliation_runs", "reconciliation_differences"}


def test_defaults(Session):
    with Session() as session:
        run = _run(session)
        session.add(_difference(run))
        session.commit()
        difference = session.query(ReconciliationDifference).one()
        assert run.status == RunStatus.RUNNING.value
        assert (
            run.files_read,
            run.records_read,
            run.rows_rejected,
            run.matched,
            run.differences,
        ) == (0,) * 5
        assert difference.status == DifferenceStatus.PENDING.value


def test_one_run_per_day(Session):
    with Session() as session:
        _run(session)
        session.commit()
        with pytest.raises(IntegrityError):
            _run(session)


def test_one_difference_per_day_partner_type_and_reference(Session):
    with Session() as session:
        run = _run(session)
        session.add(_difference(run))
        session.commit()
        # Another type for the same reference is fine (D4: DATE_OFF gives two).
        session.add(_difference(run, type="MISSING_IN_PARTNER", id=uuid.uuid4()))
        session.commit()
        session.add(_difference(run, id=uuid.uuid4()))
        with pytest.raises(IntegrityError):
            session.commit()
