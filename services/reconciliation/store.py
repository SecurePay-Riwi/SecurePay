"""Step 3: turn the match into differences and save them (HU-38 to HU-41,
Yulianis).

    load_rows(match_path)    the MatchRows that match wrote for a day
    classify(row)            the differences of one row (pure, no database)
    save(session, ...)       the run of the day (DONE) and its differences
    handler(event)           Step Functions step 3, in AWS

RN-10 and D4: ONLY_PAGOSEGURO -> MISSING_IN_PARTNER, ONLY_PARTNER ->
MISSING_IN_PAGOSEGURO, AMOUNT_OFF -> AMOUNT_MISMATCH, DATE_OFF -> one of
each missing type. A difference is unique per (run_day, partner, type,
reference) and inserted ON CONFLICT DO NOTHING, so running a day again
neither duplicates it nor reopens a RESOLVED one.

Tests: tests/test_store.py, against tests/fixtures/curated/conciliacion/
and the expected differences of tests/fixtures/extracts_report.json.
"""

import logging
from datetime import UTC, date, datetime, timedelta, timezone

from sqlalchemy.dialects.postgresql import insert

from services.reconciliation import RECON_DATA_DIR, match_dir, storage
from shared.db import SessionLocal
from shared.reconciliation import (
    DifferenceType,
    MatchRow,
    MatchStatus,
    ReconciliationDifference,
    ReconciliationRun,
    RunStatus,
    create_schema,
    match_row_from_json,
)

log = logging.getLogger(__name__)

# Bogota has no daylight saving time: the nightly run reconciles yesterday there.
BOGOTA = timezone(timedelta(hours=-5))

_schema_ready = False


def load_rows(match_path: str) -> list[MatchRow]:
    """Every part-*.json under match_path (local folder or s3://), with
    match_row_from_json. A folder without files is an empty day."""
    return [
        match_row_from_json(line)
        for path in storage.list_files(match_path, "part-*.json")
        for line in storage.read_jsonl(path)
    ]


def _difference(row: MatchRow, kind: DifferenceType) -> dict:
    """One reconciliation_differences row (without run_id and detected_at).
    MISSING_IN_PARTNER keeps only PagoSeguro's side; MISSING_IN_PAGOSEGURO
    only the partner's; AMOUNT_MISMATCH both and partner - pagoseguro."""
    ours = kind in (DifferenceType.MISSING_IN_PARTNER, DifferenceType.AMOUNT_MISMATCH)
    theirs = kind in (DifferenceType.MISSING_IN_PAGOSEGURO, DifferenceType.AMOUNT_MISMATCH)
    return {
        "run_day": row.run_day,
        "partner": row.partner,
        "type": kind.value,
        "reference": row.reference,
        "partner_reference": row.partner_reference if theirs else None,
        "currency": row.currency,
        "pagoseguro_amount": row.pagoseguro_amount if ours else None,
        "partner_amount": row.partner_amount if theirs else None,
        "amount_difference": (row.partner_amount - row.pagoseguro_amount
                              if kind is DifferenceType.AMOUNT_MISMATCH else None),
        "pagoseguro_at": row.pagoseguro_at if ours else None,
        "partner_at": row.partner_at if theirs else None,
    }


# What each match status turns into (D4: DATE_OFF is missing on both sides).
_TYPES = {
    MatchStatus.MATCHED.value: (),
    MatchStatus.ONLY_PAGOSEGURO.value: (DifferenceType.MISSING_IN_PARTNER,),
    MatchStatus.ONLY_PARTNER.value: (DifferenceType.MISSING_IN_PAGOSEGURO,),
    MatchStatus.AMOUNT_OFF.value: (DifferenceType.AMOUNT_MISMATCH,),
    MatchStatus.DATE_OFF.value: (DifferenceType.MISSING_IN_PARTNER,
                                 DifferenceType.MISSING_IN_PAGOSEGURO),
}


def classify(row: MatchRow) -> list[dict]:
    """The differences of one row, as reconciliation_differences values:
    MATCHED -> []; ONLY_PAGOSEGURO -> [MISSING_IN_PARTNER];
    ONLY_PARTNER -> [MISSING_IN_PAGOSEGURO]; AMOUNT_OFF -> [AMOUNT_MISMATCH
    with both amounts and amount_difference]; DATE_OFF -> [MISSING_IN_PARTNER,
    MISSING_IN_PAGOSEGURO] (D4)."""
    return [_difference(row, kind) for kind in _TYPES[MatchStatus(row.status).value]]


def save(session, day: date, rows: list[MatchRow], counts: dict, now: datetime) -> dict:
    """Upsert the run of `day` (DONE, counts), insert every classify() result
    ON CONFLICT DO NOTHING, one commit. Returns {"day", "matched", "differences"}.

    counts are what ingest and match returned: files_read, records,
    rejected (and matched, otherwise counted from the rows)."""
    differences = [d for row in rows for d in classify(row)]
    matched = counts.get("matched")
    if matched is None:
        matched = sum(1 for r in rows if r.status == MatchStatus.MATCHED.value)

    run = {
        "status": RunStatus.DONE.value,
        "finished_at": now,
        "files_read": counts.get("files_read", 0),
        "records_read": counts.get("records", 0),
        "rows_rejected": counts.get("rejected", 0),
        "matched": matched,
        "differences": len(differences),
        "error": None,
    }
    # In AWS nobody marked the run RUNNING before: insert it with started_at.
    run_id = session.execute(
        insert(ReconciliationRun)
        .values(run_day=day, started_at=now, **run)
        .on_conflict_do_update(index_elements=[ReconciliationRun.run_day], set_=run)
        .returning(ReconciliationRun.id)
    ).scalar_one()

    if differences:
        session.execute(
            insert(ReconciliationDifference)
            .values([{**d, "run_id": run_id, "detected_at": now} for d in differences])
            .on_conflict_do_nothing(index_elements=["run_day", "partner", "type", "reference"])
        )
    session.commit()
    log.info("Reconciliation %s: %d matched, %d differences", day, matched, len(differences))
    return {"day": day.isoformat(), "matched": matched, "differences": len(differences)}


def handler(event, context=None) -> dict:  # Step Functions step 3
    """event = what ingest returned (day, files_read, records, rejected).
    create_schema() on the first call (cold start); match_path =
    match_dir(RECON_DATA_DIR, day); matched counted from the rows (EMR's
    output does not reach Step Functions) -> load_rows + save."""
    global _schema_ready
    event = event or {}
    day = (date.fromisoformat(event["day"]) if event.get("day")
           else datetime.now(BOGOTA).date() - timedelta(days=1))
    rows = load_rows(match_dir(RECON_DATA_DIR, day))
    counts = {k: event[k] for k in ("files_read", "records", "rejected") if k in event}
    with SessionLocal() as session:
        if not _schema_ready:
            create_schema(session)
            _schema_ready = True
        return save(session, day, rows, counts, datetime.now(UTC))
