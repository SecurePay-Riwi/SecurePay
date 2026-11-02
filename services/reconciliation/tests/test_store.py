"""Step 3: classify the match rows into differences and save them
(HU-38 to HU-40, RN-10, D4).

classify() is pure; save() and handler() run against PostgreSQL in a
schema of their own. The day is the fixture day (2026-10-05): its match
output and its expected differences are in tests/fixtures/.
"""

import shutil
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from services.reconciliation import store
from services.reconciliation.tests.conftest import DAY, MATCH
from shared.reconciliation import (
    DifferenceStatus,
    MatchRow,
    ReconciliationDifference,
    ReconciliationRun,
    RunStatus,
    create_schema,
)
from shared.tests.isolated_db import isolated_sessions

NOW = datetime(2026, 10, 6, 7, 30, tzinfo=UTC)
COUNTS = {"files_read": 4, "records": 11, "rejected": 2}
OURS_AT = datetime(2026, 10, 5, 22, 15, tzinfo=UTC)
THEIRS_AT = datetime(2026, 10, 5, 22, 20, tzinfo=UTC)


def _row(status, *, currency="USD", ours="20.00", theirs="20.00", reference="ref-1",
         partner="cajeros_express", partner_reference="CX000000009",
         ours_at=OURS_AT, theirs_at=THEIRS_AT):
    """A MatchRow as match writes it; the missing side is None."""
    only_ours = status == "ONLY_PAGOSEGURO"
    only_theirs = status == "ONLY_PARTNER"
    return MatchRow(
        run_day=DAY,
        partner=partner,
        status=status,
        reference=reference,
        partner_reference=None if only_ours else partner_reference,
        currency=currency,
        pagoseguro_amount=None if only_theirs else Decimal(ours),
        partner_amount=None if only_ours else Decimal(theirs),
        pagoseguro_at=None if only_theirs else ours_at,
        partner_at=None if only_ours else theirs_at,
    )


@pytest.fixture
def sessions():
    with isolated_sessions("reconciliation_store_test") as factory:
        with factory() as s:
            create_schema(s)
        yield factory


def _differences(factory) -> list[ReconciliationDifference]:
    with factory() as s:
        return s.scalars(select(ReconciliationDifference).order_by(
            ReconciliationDifference.partner, ReconciliationDifference.reference,
            ReconciliationDifference.type)).all()


def _key(d) -> tuple:
    """A difference as the answer key writes it."""
    def text(value):
        return None if value is None else format(Decimal(value), "f")

    get = d.get if isinstance(d, dict) else lambda k: getattr(d, k)
    day = get("day") if isinstance(d, dict) else get("run_day").isoformat()
    return (get("type"), get("partner"), day, get("reference"), get("currency"),
            text(get("pagoseguro_amount")), text(get("partner_amount")))


# --- classify(): one row, no database -----------------------------------------

def test_a_matched_row_is_not_a_difference():
    assert store.classify(_row("MATCHED")) == []


def test_ours_not_in_the_file_is_missing_at_the_partner():  # HU-38
    [d] = store.classify(_row("ONLY_PAGOSEGURO", ours="60.00"))

    assert d["type"] == "MISSING_IN_PARTNER"
    assert (d["pagoseguro_amount"], d["pagoseguro_at"]) == (Decimal("60.00"), OURS_AT)
    assert (d["partner_amount"], d["partner_at"], d["partner_reference"]) == (None, None, None)
    assert d["amount_difference"] is None
    assert (d["run_day"], d["partner"], d["reference"], d["currency"]) == (
        DAY, "cajeros_express", "ref-1", "USD")


def test_the_partners_not_ours_is_missing_at_pagoseguro():  # HU-39
    [d] = store.classify(_row("ONLY_PARTNER", theirs="5.25", partner="qr_pagos",
                              partner_reference="QR000000003"))

    assert d["type"] == "MISSING_IN_PAGOSEGURO"
    assert (d["partner_amount"], d["partner_at"]) == (Decimal("5.25"), THEIRS_AT)
    assert d["partner_reference"] == "QR000000003"
    assert (d["pagoseguro_amount"], d["pagoseguro_at"]) == (None, None)
    assert d["amount_difference"] is None


@pytest.mark.parametrize(("currency", "ours", "theirs", "difference"), [
    ("COP", "123456.78", "123457.00", "0.22"),
    ("USD", "100.00", "99.50", "-0.50"),
    ("EUR", "88.91", "89.00", "0.09"),
    ("JPY", "1500", "1502", "2"),
])
def test_an_amount_off_keeps_both_amounts_and_the_difference(currency, ours, theirs, difference):  # HU-40
    [d] = store.classify(_row("AMOUNT_OFF", currency=currency, ours=ours, theirs=theirs))

    assert d["type"] == "AMOUNT_MISMATCH"
    assert d["currency"] == currency
    assert (d["pagoseguro_amount"], d["partner_amount"]) == (Decimal(ours), Decimal(theirs))
    assert d["amount_difference"] == Decimal(difference)  # partner - pagoseguro
    assert (d["pagoseguro_at"], d["partner_at"]) == (OURS_AT, THEIRS_AT)


def test_one_cent_apart_is_matched_not_a_difference():  # RN-10: the limit is included
    # match gives MATCHED for 10.00 vs 10.01; classify() writes nothing for it.
    assert store.classify(_row("MATCHED", ours="10.00", theirs="10.01")) == []


def test_a_date_off_is_missing_on_both_sides():  # D4
    ours_at = datetime(2026, 10, 4, 3, 10, tzinfo=UTC)
    theirs_at = datetime(2026, 10, 6, 1, 0, tzinfo=UTC)

    first, second = store.classify(_row("DATE_OFF", currency="EUR", ours="50.00", theirs="50.00",
                                        ours_at=ours_at, theirs_at=theirs_at))

    assert (first["type"], first["pagoseguro_at"], first["partner_at"]) == (
        "MISSING_IN_PARTNER", ours_at, None)
    assert (second["type"], second["partner_at"], second["pagoseguro_at"]) == (
        "MISSING_IN_PAGOSEGURO", theirs_at, None)
    assert first["reference"] == second["reference"]


def test_an_unknown_status_is_an_error():
    with pytest.raises(ValueError):
        store.classify(_row("SOMETHING_ELSE"))


# --- load_rows(): the match output ----------------------------------------------

def test_load_rows_reads_the_fixture_day():
    rows = store.load_rows(MATCH)

    assert len(rows) == 13
    assert {r.run_day for r in rows} == {DAY}
    assert sum(1 for r in rows if r.status == "MATCHED") == 8


def test_a_day_without_match_files_is_empty(tmp_path):
    assert store.load_rows(str(tmp_path / "nothing")) == []


# --- save(): the run and its differences ---------------------------------------

def test_the_fixture_day_gives_the_expected_differences(sessions, report):
    with sessions() as s:
        result = store.save(s, DAY, store.load_rows(MATCH), {**COUNTS, "matched": 8}, NOW)

    assert result == {"day": "2026-10-05", "matched": 8, "differences": 6}
    saved = _differences(sessions)
    assert sorted(_key(d) for d in saved) == sorted(_key(d) for d in report["expected_differences"])
    assert {d.status for d in saved} == {DifferenceStatus.PENDING.value}
    assert {d.detected_at for d in saved} == {NOW}
    amount = next(d for d in saved if d.type == "AMOUNT_MISMATCH")
    assert amount.amount_difference == Decimal("0.22")


def test_the_run_is_done_with_its_counts(sessions, report):
    with sessions() as s:
        store.save(s, DAY, store.load_rows(MATCH), COUNTS, NOW)  # matched counted from the rows
        run = s.scalars(select(ReconciliationRun)).one()

    expected = report["expected_run"]
    assert run.status == RunStatus.DONE.value
    assert (run.files_read, run.records_read, run.rows_rejected, run.matched, run.differences) == (
        expected["files_read"], expected["records"], expected["rejected"],
        expected["matched"], expected["differences"])
    assert (run.started_at, run.finished_at, run.error) == (NOW, NOW, None)


def test_save_closes_a_running_run(sessions):
    started = datetime(2026, 10, 6, 7, 0, tzinfo=UTC)
    with sessions() as s:
        s.add(ReconciliationRun(run_day=DAY, status=RunStatus.RUNNING.value, started_at=started))
        s.commit()
        store.save(s, DAY, [], COUNTS, NOW)
        run = s.scalars(select(ReconciliationRun)).one()

    assert (run.status, run.started_at, run.finished_at) == (RunStatus.DONE.value, started, NOW)


def test_running_the_day_again_does_not_duplicate(sessions):
    rows = store.load_rows(MATCH)
    with sessions() as s:
        store.save(s, DAY, rows, COUNTS, NOW)
        store.save(s, DAY, rows, COUNTS, datetime(2026, 10, 7, 7, 30, tzinfo=UTC))
        assert len(s.scalars(select(ReconciliationRun)).all()) == 1

    saved = _differences(sessions)
    assert len(saved) == 6
    assert {d.detected_at for d in saved} == {NOW}  # the first detection stays


def test_a_day_with_thousands_of_differences_is_saved(sessions):
    # A partner's file missing: every one of ours is MISSING_IN_PARTNER, more
    # than one INSERT can take (PostgreSQL's limit is 65535 parameters).
    rows = [_row("ONLY_PAGOSEGURO", reference=f"ref-{i}") for i in range(6000)]
    with sessions() as s:
        result = store.save(s, DAY, rows, COUNTS, NOW)
        run = s.scalars(select(ReconciliationRun)).one()

    assert result["differences"] == 6000
    assert (run.status, run.differences) == (RunStatus.DONE.value, 6000)
    assert len(_differences(sessions)) == 6000


def test_a_resolved_difference_is_not_reopened(sessions):
    rows = [_row("ONLY_PAGOSEGURO")]
    with sessions() as s:
        store.save(s, DAY, rows, COUNTS, NOW)
        difference = s.scalars(select(ReconciliationDifference)).one()
        difference.status = DifferenceStatus.RESOLVED.value
        difference.resolved_by = "tesoreria"
        s.commit()
        store.save(s, DAY, rows, COUNTS, NOW)

    [d] = _differences(sessions)
    assert (d.status, d.resolved_by) == (DifferenceStatus.RESOLVED.value, "tesoreria")


# --- handler(): Step Functions step 3 -----------------------------------------

def test_the_handler_reads_the_match_of_the_day(sessions, tmp_path, monkeypatch):
    target = tmp_path / "curated" / "conciliacion" / "fecha=2026-10-05"
    target.mkdir(parents=True)
    shutil.copy(Path(MATCH) / "part-00000.json", target / "part-00000.json")
    monkeypatch.setattr(store, "RECON_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(store, "SessionLocal", sessions)
    monkeypatch.setattr(store, "_schema_ready", False)

    result = store.handler({"day": "2026-10-05", **COUNTS})

    assert result == {"day": "2026-10-05", "matched": 8, "differences": 6}
    assert len(_differences(sessions)) == 6


def test_the_handler_without_a_day_takes_yesterday_in_bogota(sessions, tmp_path, monkeypatch):
    monkeypatch.setattr(store, "RECON_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(store, "SessionLocal", sessions)
    yesterday = datetime.now(store.BOGOTA).date().toordinal() - 1

    result = store.handler({})

    assert date.fromisoformat(result["day"]).toordinal() == yesterday
    assert result["differences"] == 0
