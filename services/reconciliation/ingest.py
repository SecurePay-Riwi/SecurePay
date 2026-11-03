"""Step 1: read the four partners' files of a day (HU-36, Jorge).

For each partner, the latest version of its file of the day
(<source>/<partner>/fecha=YYYY-MM-DD/<partner>_YYYYMMDD_vN.<ext>) is read
with its reader in parsers.py. The formats are in
doc-website/docs/components/partner-statements.mdx and the fixtures in
tests/fixtures/extractos/ (expected output: tests/fixtures/curated/extractos/).
"""

import logging
import re
from datetime import UTC, date, datetime, timedelta

from services.reconciliation import (
    RECON_DATA_DIR,
    STATEMENTS_SOURCE,
    records_dir,
    storage,
)
from services.reconciliation.parsers import READERS
from shared.reconciliation import (
    PARTNER_UTC_OFFSET,
    RejectedRow,
    StatementRecord,
    to_json,
)

log = logging.getLogger(__name__)

_VERSION = re.compile(r"_v(\d+)\.[^.]+$")


def latest_file(source: str, partner: str, day: date) -> str | None:
    """The path of the highest version of a partner's file of `day`."""
    reader = READERS[partner]
    folder = storage.join(source, partner, f"fecha={day.isoformat()}")
    pattern = f"{partner}_{day:%Y%m%d}_v*.{reader.extension}"
    versions = {}
    for path in storage.list_files(folder, pattern):
        found = _VERSION.search(path)
        if found:
            versions[int(found.group(1))] = path
    return versions[max(versions)] if versions else None


def read_files(
    day: date, source: str
) -> tuple[list[StatementRecord], list[RejectedRow], list[str]]:
    """read_day() plus the names of the files read (an empty file counts)."""
    records, rejected, files = [], [], []
    for partner, reader in READERS.items():
        path = latest_file(source, partner, day)
        if path is None:
            expected = f"{partner}_{day:%Y%m%d}_v1.{reader.extension}"
            rejected.append(
                RejectedRow(
                    partner=partner,
                    file_name=expected,
                    line_number=0,
                    raw="",
                    reason="file missing",
                )
            )
            continue
        name = path.replace("\\", "/").rsplit("/", 1)[-1]
        try:
            text = storage.read_text(path)
        except UnicodeDecodeError:
            rejected.append(
                RejectedRow(
                    partner=partner,
                    file_name=name,
                    line_number=0,
                    raw="",
                    reason="file is not UTF-8 text",
                )
            )
            continue
        parsed = reader.parse(text, name, day)
        records += parsed.records
        rejected += parsed.rejected
        files.append(name)
    log.info(
        "Read %s: %d files, %d records, %d rejected",
        day,
        len(files),
        len(records),
        len(rejected),
    )
    return records, rejected, files


def read_day(day: date, source: str) -> tuple[list[StatementRecord], list[RejectedRow]]:
    """The 4 partners' files of `day` from `source` (a local folder laid out
    like generated/extractos/, or "s3://<bucket>/raw/extractos"). Only the
    latest version of each partner's file (_v2 over _v1). Malformed rows and
    files whose control record does not add up go to the rejected list with
    their reason; the rest of the file is still read. A missing file is a
    rejected row with reason "file missing"."""
    records, rejected, _ = read_files(day, source)
    return records, rejected


def run(day: date, source: str, target: str) -> dict:
    """read_day + write <target>/curated/extractos/fecha=<day>/records.jsonl
    and rejects.jsonl (to_json per line). Returns
    {"day", "records_path", "files_read", "records", "rejected"}."""
    records, rejected, files = read_files(day, source)
    folder = records_dir(target, day)
    records_path = storage.join(folder, "records.jsonl")
    storage.write_jsonl(records_path, [to_json(r) for r in records])
    storage.write_jsonl(
        storage.join(folder, "rejects.jsonl"), [to_json(r) for r in rejected]
    )
    return {
        "day": day.isoformat(),
        "records_path": records_path,
        "files_read": len(files),
        "records": len(records),
        "rejected": len(rejected),
    }


def yesterday_in_bogota(now: datetime) -> date:
    offset = timedelta(hours=PARTNER_UTC_OFFSET["red_corresponsales"])
    return (now + offset).date() - timedelta(days=1)


def handler(event, context=None) -> dict:  # Step Functions step 1
    """event {"day": "YYYY-MM-DD"} (absent: yesterday in Bogota) -> run()."""
    raw_day = (event or {}).get("day")
    day = (
        date.fromisoformat(raw_day)
        if raw_day
        else yesterday_in_bogota(datetime.now(UTC))
    )
    return run(day, STATEMENTS_SOURCE, RECON_DATA_DIR)
