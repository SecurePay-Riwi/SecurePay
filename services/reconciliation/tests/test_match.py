"""The match (HU-37): reconcile() in Spark and match_day(), its plain
Python reference, against the fixture day and the edges of RN-10.

Every edge case runs on both implementations. The Spark tests need Java
(17 or later) and skip with a notice without it. No database needed.
"""

import itertools
import json
import shutil
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from services.reconciliation import match, storage
from services.reconciliation.tests.conftest import DAY, DECISIONS, MATCH, RECORDS
from shared.reconciliation import (
    StatementRecord,
    match_row_from_json,
    partner_for,
    to_json,
)

AT = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def spark():
    if shutil.which("java") is None:
        pytest.skip(
            "Spark needs Java 17 or later: install it to run the match tests in Spark"
        )
    return match.session()


def _written(folder) -> list[dict]:
    return [
        d
        for p in storage.list_files(str(folder), "part-*.json")
        for d in storage.read_jsonl(p)
    ]


def test_fixture_day_gives_the_expected_rows(spark, tmp_path):
    result = match.reconcile(spark, DAY, RECORDS, DECISIONS, str(tmp_path))
    assert _written(tmp_path) == storage.read_jsonl(f"{MATCH}/part-00000.json")
    assert result == {
        "day": "2026-10-05",
        "match_path": str(tmp_path),
        "matched": 8,
        "unmatched": 5,
    }


def test_spark_and_the_reference_agree_on_the_fixture_day(spark, tmp_path):
    match.reconcile(spark, DAY, RECORDS, DECISIONS, str(tmp_path))
    reference = match.match_day(
        DAY, match.read_records(RECORDS), match.read_decisions(DECISIONS, DAY)
    )
    assert [match_row_from_json(d) for d in _written(tmp_path)] == reference


def test_a_day_run_again_replaces_its_rows(spark, tmp_path):
    for _ in range(2):
        match.reconcile(spark, DAY, RECORDS, DECISIONS, str(tmp_path))
    assert len(_written(tmp_path)) == 13


def test_without_spark_io_the_files_go_through_storage(spark, tmp_path, monkeypatch):
    # What happens with s3:// paths in local mode (LocalStack).
    monkeypatch.setattr(match, "_spark_reads", lambda spark, path: False)
    match.reconcile(spark, DAY, RECORDS, DECISIONS, str(tmp_path))
    assert storage.read_jsonl(str(tmp_path / "part-00000.json")) == storage.read_jsonl(
        f"{MATCH}/part-00000.json"
    )


def test_an_empty_day_writes_nothing_to_match(spark, tmp_path):
    records = tmp_path / "records.jsonl"
    records.write_text("", encoding="utf-8")
    result = match.reconcile(
        spark, DAY, str(records), str(tmp_path / "none"), str(tmp_path / "out")
    )
    assert result["matched"] == 0 and result["unmatched"] == 0


def test_main_writes_the_rows(spark, tmp_path, capsys):
    match.main(
        [
            "--day",
            "2026-10-05",
            "--records",
            RECORDS,
            "--decisions",
            DECISIONS,
            "--output",
            str(tmp_path),
        ]
    )
    assert '"matched": 8' in capsys.readouterr().out
    assert [match_row_from_json(d) for d in _written(tmp_path)]


def test_partner_column_is_partner_for(spark):
    types = ["RECARGA", "RETIRO", "QR", "P2P"]
    channels = ["APP", "WEB", "CORRESPONSAL", "CAJERO", "POS"]
    frame = spark.createDataFrame(
        list(itertools.product(types, channels)), "type string, channel string"
    )
    got = {
        (r["type"], r["channel"]): r["partner"]
        for r in frame.select(
            "type",
            "channel",
            match.partner_column(frame["type"], frame["channel"]).alias("partner"),
        ).collect()
    }
    for (tx_type, channel), partner in got.items():
        expected = partner_for(tx_type, channel)
        assert partner == (expected.value if expected else None)


def _event(
    tx_id="t1", decision="APPROVE", tx_type="QR", channel="APP", amount="10.00", at=AT
):
    return {
        "transaction": {
            "id": tx_id,
            "type": tx_type,
            "channel": channel,
            "amount": amount,
            "currency": "USD",
            "transaction_date": at.isoformat(),
        },
        "decision": {"decision": decision},
    }


def _record(reference="t1", amount="10.00", at=AT):
    return StatementRecord(
        "qr_pagos",
        DAY,
        "qr_pagos_20261005_v1.txt",
        3,
        reference,
        "QR000000001",
        "QR",
        "USD",
        Decimal(amount),
        at,
    )


def _reference(tmp_path, records, events):
    return [r.status for r in match.match_day(DAY, records, events)]


def _spark(tmp_path, records, events):
    """The same case through reconcile(): records.jsonl and the events in
    raw/decisiones/fecha=<their UTC day>/, in a folder of its own."""
    tmp_path = tmp_path / uuid.uuid4().hex
    tmp_path.mkdir()
    records_path = tmp_path / "records.jsonl"
    records_path.write_text(
        "".join(json.dumps(to_json(r)) + "\n" for r in records), encoding="utf-8"
    )
    for i, event in enumerate(events):
        day = event["transaction"]["transaction_date"][:10]
        folder = tmp_path / "decisiones" / f"fecha={day}"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"part-{i:04d}.jsonl").write_text(
            json.dumps(event) + "\n", encoding="utf-8"
        )
    output = tmp_path / "out"
    match.reconcile(
        match.session(),
        DAY,
        str(records_path),
        str(tmp_path / "decisiones"),
        str(output),
    )
    return [d["status"] for d in _written(output)]


@pytest.fixture(params=["reference", "spark"])
def status(request, tmp_path):
    if request.param == "spark":
        request.getfixturevalue("spark")
        return lambda records, events: _spark(tmp_path, records, events)
    return lambda records, events: _reference(tmp_path, records, events)


def test_amount_tolerance_includes_one_cent(status):
    assert status([_record(amount="10.01")], [_event()]) == ["MATCHED"]
    assert status([_record(amount="9.99")], [_event()]) == ["MATCHED"]


def test_two_cents_is_amount_off(status):
    assert status([_record(amount="10.02")], [_event()]) == ["AMOUNT_OFF"]


def test_date_tolerance_includes_one_day(status):
    assert status([_record(at=AT + timedelta(days=1))], [_event()]) == ["MATCHED"]


def test_one_day_and_one_second_is_date_off(status):
    assert status([_record(at=AT + timedelta(days=1, seconds=1))], [_event()]) == [
        "DATE_OFF"
    ]


def test_date_is_checked_before_amount(status):
    assert status([_record(amount="99.00", at=AT - timedelta(days=2))], [_event()]) == [
        "DATE_OFF"
    ]


def test_repeated_raw_lines_count_once(status):
    assert status([], [_event(), _event()]) == ["ONLY_PAGOSEGURO"]


def test_a_reference_twice_in_the_files_counts_once(status):
    assert status([_record(amount="10.00"), _record(amount="50.00")], [_event()]) == [
        "MATCHED"
    ]


def test_p2p_hold_and_reject_do_not_count(status):
    events = [
        _event("p", tx_type="P2P"),
        _event("h", decision="HOLD"),
        _event("r", decision="REJECT"),
    ]
    assert status([], events) == []


def test_a_held_transaction_in_the_file_is_only_partner(status):
    assert status([_record("h")], [_event("h", decision="HOLD")]) == ["ONLY_PARTNER"]


def test_ours_of_another_partner_day_only_counts_with_a_record(status):
    tomorrow = AT + timedelta(days=1)
    assert status([], [_event(at=tomorrow)]) == []
    assert status([_record(at=tomorrow)], [_event(at=tomorrow)]) == ["MATCHED"]


def test_a_bogota_partner_day_is_five_hours_behind(status):
    # 03:00 UTC on the 6th is 22:00 on the 5th in Bogota: cajeros_express's file of the 5th.
    late = datetime(2026, 10, 6, 3, 0, tzinfo=UTC)
    assert status([], [_event(tx_type="RETIRO", channel="CAJERO", at=late)]) == [
        "ONLY_PAGOSEGURO"
    ]
    assert status([], [_event(tx_type="QR", at=late)]) == []


def test_window_is_the_day_and_its_neighbours():
    assert match.window(date(2026, 10, 1)) == [
        date(2026, 9, 30),
        date(2026, 10, 1),
        date(2026, 10, 2),
    ]
