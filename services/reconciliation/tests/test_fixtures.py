"""The fixtures agree with each other: the files, what ingest and match
must write, and the answer key. No database needed."""

from collections import Counter

from services.reconciliation import storage
from services.reconciliation.tests.conftest import MATCH, RECORDS, REJECTS
from shared.reconciliation import (
    DifferenceType,
    MatchStatus,
    match_row_from_json,
    record_from_json,
)

# D4: what each match status becomes (store.classify, HU-38 to HU-40).
EXPECTED_TYPES = {
    MatchStatus.MATCHED: [],
    MatchStatus.ONLY_PAGOSEGURO: [DifferenceType.MISSING_IN_PARTNER],
    MatchStatus.ONLY_PARTNER: [DifferenceType.MISSING_IN_PAGOSEGURO],
    MatchStatus.AMOUNT_OFF: [DifferenceType.AMOUNT_MISMATCH],
    MatchStatus.DATE_OFF: [DifferenceType.MISSING_IN_PARTNER, DifferenceType.MISSING_IN_PAGOSEGURO],
}


def _rows():
    return [match_row_from_json(d) for d in storage.read_jsonl(f"{MATCH}/part-00000.json")]


def test_every_status_and_type_is_in_the_fixtures():
    statuses = {row.status for row in _rows()}
    assert statuses == {s.value for s in MatchStatus}


def test_records_and_rejects_parse(report):
    records = [record_from_json(d) for d in storage.read_jsonl(RECORDS)]
    rejects = storage.read_jsonl(REJECTS)
    assert len(records) == report["expected_run"]["records"]
    assert len(rejects) == report["expected_run"]["rejected"]
    assert len({r.file_name for r in records}) == report["expected_run"]["files_read"]
    # Only the latest version of each partner's file is read.
    latest = {f["file"].rsplit("/", 1)[-1] for f in report["files"] if f["latest"]}
    assert {r.file_name for r in records} == latest


def test_answer_key_is_the_match_rows_classified(report):
    found = Counter()
    for row in _rows():
        for kind in EXPECTED_TYPES[MatchStatus(row.status)]:
            found[(kind.value, row.partner, row.reference)] += 1
    expected = Counter((d["type"], d["partner"], d["reference"]) for d in report["expected_differences"])
    assert found == expected
    assert report["expected_run"]["differences"] == sum(expected.values())
    assert report["expected_run"]["matched"] == sum(r.status == "MATCHED" for r in _rows())
