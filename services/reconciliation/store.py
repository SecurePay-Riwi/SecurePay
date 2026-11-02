"""Step 3: turn the match into differences and save them (HU-38 to HU-41,
Yulianis).

Step 0 leaves the signatures of contract C2 returning nothing. The input
for tests is tests/fixtures/curated/conciliacion/ and the expected
differences are in tests/fixtures/extracts_report.json.
"""

import logging
from datetime import date, datetime

from shared.reconciliation import MatchRow

log = logging.getLogger(__name__)


def load_rows(match_path: str) -> list[MatchRow]:
    """Every part-*.json under match_path (local folder or s3://), with
    match_row_from_json."""
    return []


def classify(row: MatchRow) -> list[dict]:
    """The differences of one row, as reconciliation_differences values:
    MATCHED -> []; ONLY_PAGOSEGURO -> [MISSING_IN_PARTNER];
    ONLY_PARTNER -> [MISSING_IN_PAGOSEGURO]; AMOUNT_OFF -> [AMOUNT_MISMATCH
    with both amounts and amount_difference]; DATE_OFF -> [MISSING_IN_PARTNER,
    MISSING_IN_PAGOSEGURO] (D4)."""
    return []


def save(session, day: date, rows: list[MatchRow], counts: dict, now: datetime) -> dict:
    """Upsert the run of `day` (DONE, counts), insert every classify() result
    ON CONFLICT DO NOTHING, one commit. Returns {"day", "matched", "differences"}."""
    log.warning("store.save is a step 0 stub (HU-38): nothing saved for %s", day)
    return {"day": day.isoformat(), "matched": 0, "differences": 0}


def handler(event, context=None) -> dict:  # Step Functions step 3
    """event = what ingest and match returned (day, match_path, files_read,
    records, rejected) -> load_rows + save."""
    return {"day": (event or {}).get("day"), "matched": 0, "differences": 0}
