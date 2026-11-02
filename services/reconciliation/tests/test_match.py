"""The reference match of step 0 (match.match_day, plain Python).

HU-37 moves reconcile() to Spark and checks it against the same fixtures
and these edge cases. No database needed.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from services.reconciliation import match, storage
from services.reconciliation.tests.conftest import DAY, DECISIONS, MATCH, RECORDS
from shared.reconciliation import StatementRecord, match_row_from_json

AT = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


def test_fixture_day_gives_the_expected_rows(tmp_path):
    result = match.reconcile(None, DAY, RECORDS, DECISIONS, str(tmp_path))
    got = storage.read_jsonl(str(tmp_path / "part-00000.json"))
    assert got == storage.read_jsonl(f"{MATCH}/part-00000.json")
    assert result == {"day": "2026-10-05", "match_path": str(tmp_path), "matched": 8, "unmatched": 5}


def test_main_writes_the_rows(tmp_path, capsys):
    match.main(["--day", "2026-10-05", "--records", RECORDS, "--decisions", DECISIONS,
                "--output", str(tmp_path)])
    assert '"matched": 8' in capsys.readouterr().out
    assert [match_row_from_json(d) for d in storage.read_jsonl(str(tmp_path / "part-00000.json"))]


def _event(tx_id="t1", decision="APPROVE", tx_type="QR", channel="APP", amount="10.00", at=AT):
    return {
        "transaction": {"id": tx_id, "type": tx_type, "channel": channel, "amount": amount,
                        "currency": "USD", "transaction_date": at.isoformat()},
        "decision": {"decision": decision},
    }


def _record(reference="t1", amount="10.00", at=AT):
    return StatementRecord("qr_pagos", DAY, "qr_pagos_20261005_v1.txt", 3, reference,
                           "QR000000001", "QR", "USD", Decimal(amount), at)


def _status(records, events):
    return [r.status for r in match.match_day(DAY, records, events)]


def test_amount_tolerance_includes_one_cent():
    assert _status([_record(amount="10.01")], [_event()]) == ["MATCHED"]
    assert _status([_record(amount="10.02")], [_event()]) == ["AMOUNT_OFF"]


def test_date_tolerance_includes_one_day():
    assert _status([_record(at=AT + timedelta(days=1))], [_event()]) == ["MATCHED"]
    assert _status([_record(at=AT + timedelta(days=1, seconds=1))], [_event()]) == ["DATE_OFF"]


def test_repeated_raw_lines_count_once():
    assert _status([], [_event(), _event()]) == ["ONLY_PAGOSEGURO"]


def test_p2p_hold_and_reject_do_not_count():
    events = [_event("p", tx_type="P2P"), _event("h", decision="HOLD"), _event("r", decision="REJECT")]
    assert _status([], events) == []
    assert _status([_record("h")], events) == ["ONLY_PARTNER"]


def test_ours_of_another_partner_day_only_counts_with_a_record():
    tomorrow = AT + timedelta(days=1)
    assert _status([], [_event(at=tomorrow)]) == []
    assert _status([_record(at=tomorrow)], [_event(at=tomorrow)]) == ["MATCHED"]


def test_window_is_the_day_and_its_neighbours():
    assert match.window(date(2026, 10, 1)) == [date(2026, 9, 30), date(2026, 10, 1), date(2026, 10, 2)]
