"""Step 1: read the four partners' files of a day (HU-36, Jorge).

Step 0 leaves the signatures of contract C2: read_day() returns nothing
yet, so the rest of the flow runs with an empty day. The formats are in
doc-website/docs/components/partner-statements.mdx and the fixtures in
tests/fixtures/extractos/ (expected output: tests/fixtures/curated/extractos/).
"""

import logging
from datetime import UTC, date, datetime, timedelta

from services.reconciliation import RECON_DATA_DIR, STATEMENTS_SOURCE, records_dir, storage
from shared.reconciliation import PARTNER_UTC_OFFSET, RejectedRow, StatementRecord, to_json

log = logging.getLogger(__name__)


def read_day(day: date, source: str) -> tuple[list[StatementRecord], list[RejectedRow]]:
    """The 4 partners' files of `day` from `source` (a local folder laid out
    like generated/extractos/, or "s3://<bucket>/raw/extractos"). Only the
    latest version of each partner's file (_v2 over _v1). Malformed rows and
    files whose control record does not add up go to the rejected list with
    their reason; the rest of the file is still read. A missing file is a
    rejected row with reason "file missing"."""
    log.warning("ingest.read_day is a step 0 stub (HU-36): no records for %s", day)
    return [], []


def run(day: date, source: str, target: str) -> dict:
    """read_day + write <target>/curated/extractos/fecha=<day>/records.jsonl
    and rejects.jsonl (to_json per line). Returns
    {"day", "records_path", "files_read", "records", "rejected"}."""
    records, rejected = read_day(day, source)
    folder = records_dir(target, day)
    records_path = storage.join(folder, "records.jsonl")
    storage.write_jsonl(records_path, [to_json(r) for r in records])
    storage.write_jsonl(storage.join(folder, "rejects.jsonl"), [to_json(r) for r in rejected])
    return {
        "day": day.isoformat(),
        "records_path": records_path,
        "files_read": len({r.file_name for r in records}),
        "records": len(records),
        "rejected": len(rejected),
    }


def yesterday_in_bogota(now: datetime) -> date:
    offset = timedelta(hours=PARTNER_UTC_OFFSET["red_corresponsales"])
    return (now + offset).date() - timedelta(days=1)


def handler(event, context=None) -> dict:  # Step Functions step 1
    """event {"day": "YYYY-MM-DD"} (absent: yesterday in Bogota) -> run()."""
    raw_day = (event or {}).get("day")
    day = date.fromisoformat(raw_day) if raw_day else yesterday_in_bogota(datetime.now(UTC))
    return run(day, STATEMENTS_SOURCE, RECON_DATA_DIR)
