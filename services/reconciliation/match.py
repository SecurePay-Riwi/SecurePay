"""Step 2: match the partners' records with the engine's decisions (HU-37).

Contract C2: reconcile() reads the records of a day and the decisions of
the window day-1..day+1, and writes one MatchRow per reference.

Step 0 leaves a reference version in plain Python (match_day()), without
Spark, so the other steps and their tests have a match to work with. HU-37
moves reconcile() to PySpark (local mode in tests, EMR Serverless in AWS)
and keeps match_day() as the reference its tests compare against.

The rules (RN-10, D3, D4):
- PagoSeguro side: APPROVE decisions that are not P2P, once per
  transaction id (raw/decisiones may repeat a line), whose partner_day()
  is the day. Partners do not see transfers inside the wallet nor what
  was rejected or held.
- Same reference on both sides: DATE_OFF when the times are more than
  DATE_TOLERANCE_DAYS apart, else AMOUNT_OFF when the amounts differ by
  more than AMOUNT_TOLERANCE, else MATCHED. Both limits are included.
- A partner record whose reference is an APPROVE of the window but of
  another partner day still counts: its date decides.
- ONLY_PAGOSEGURO: ours, not in the file. ONLY_PARTNER: in the file, and
  not an APPROVE of the window.
"""

import argparse
import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from services.reconciliation import storage
from shared.reconciliation import (
    AMOUNT_TOLERANCE,
    DATE_TOLERANCE_DAYS,
    MatchRow,
    MatchStatus,
    StatementRecord,
    partner_day,
    partner_for,
    record_from_json,
    to_json,
)

log = logging.getLogger(__name__)

# What a partner never sees.
INTERNAL_TYPES = ("P2P",)


@dataclass(frozen=True)
class Ours:
    """One of our transactions that goes through a partner."""

    reference: str
    partner: str
    partner_day: date
    currency: str
    amount: Decimal
    at: datetime


def window(day: date) -> list[date]:
    """The days of raw/decisiones read for `day`."""
    return [day + timedelta(days=d) for d in (-1, 0, 1)]


def pagoseguro_side(events: list[dict]) -> dict[str, Ours]:
    """Our approved transactions that a partner sees, by id (once each)."""
    ours: dict[str, Ours] = {}
    for event in events:
        tx, decision = event["transaction"], event["decision"]
        if decision.get("decision") != "APPROVE" or tx["type"] in INTERNAL_TYPES:
            continue
        partner = partner_for(tx["type"], tx["channel"])
        if partner is None or str(tx["id"]) in ours:
            continue
        at = datetime.fromisoformat(tx["transaction_date"])
        ours[str(tx["id"])] = Ours(
            reference=str(tx["id"]),
            partner=partner.value,
            partner_day=partner_day(partner, at),
            currency=tx["currency"],
            amount=Decimal(str(tx["amount"])),
            at=at,
        )
    return ours


def _status(ours: Ours, record: StatementRecord) -> MatchStatus:
    if abs(record.transaction_at - ours.at) > timedelta(days=DATE_TOLERANCE_DAYS):
        return MatchStatus.DATE_OFF
    if abs(record.amount - ours.amount) > AMOUNT_TOLERANCE:
        return MatchStatus.AMOUNT_OFF
    return MatchStatus.MATCHED


def match_day(day: date, records: list[StatementRecord], events: list[dict]) -> list[MatchRow]:
    """The reference match: one MatchRow per reference, sorted by partner
    and reference. `events` are the transaction.decided events of the
    window (window(day)); `records` the partners' records of `day`."""
    in_window = pagoseguro_side(events)
    by_reference: dict[str, StatementRecord] = {}
    for record in records:
        # A reference twice in the files is one operation: the first counts.
        by_reference.setdefault(record.pagoseguro_reference, record)

    rows = []
    for reference, record in by_reference.items():
        ours = in_window.get(reference)
        rows.append(MatchRow(
            run_day=day,
            partner=record.partner,
            status=(_status(ours, record) if ours else MatchStatus.ONLY_PARTNER).value,
            reference=reference,
            partner_reference=record.partner_reference,
            currency=record.currency,
            pagoseguro_amount=ours.amount if ours else None,
            partner_amount=record.amount,
            pagoseguro_at=ours.at if ours else None,
            partner_at=record.transaction_at,
        ))
    for reference, ours in in_window.items():
        if ours.partner_day != day or reference in by_reference:
            continue
        rows.append(MatchRow(
            run_day=day,
            partner=ours.partner,
            status=MatchStatus.ONLY_PAGOSEGURO.value,
            reference=reference,
            partner_reference=None,
            currency=ours.currency,
            pagoseguro_amount=ours.amount,
            partner_amount=None,
            pagoseguro_at=ours.at,
            partner_at=None,
        ))
    return sorted(rows, key=lambda r: (r.partner, r.reference))


def read_records(records_path: str) -> list[StatementRecord]:
    return [record_from_json(d) for d in storage.read_jsonl(records_path)]


def read_decisions(decisions_path: str, day: date) -> list[dict]:
    """Every event of raw/decisiones/fecha=<d>/ for the days of the window."""
    events = []
    for d in window(day):
        for path in storage.list_files(storage.join(decisions_path, f"fecha={d.isoformat()}"), "*.jsonl"):
            events += storage.read_jsonl(path)
    return events


def reconcile(spark, day: date, records_path: str, decisions_path: str, output_path: str) -> dict:
    """PagoSeguro side: events of raw/decisiones fecha=day-1..day+1, decision
    APPROVE, type != P2P, deduplicated by transaction id, partner_for() and
    partner_day() == day. Full outer join with the records on reference.
    MATCHED when |amount diff| <= 0.01 and |date diff| <= 1 day; AMOUNT_OFF,
    DATE_OFF, ONLY_PAGOSEGURO, ONLY_PARTNER otherwise. A partner record whose
    reference is an APPROVE of the window but of another partner_day still
    counts (date check). Writes one MatchRow per reference as JSON lines under
    output_path (curated/conciliacion/fecha=<day>/). Returns {"day",
    "match_path", "matched", "unmatched"}.

    Step 0: `spark` is not used yet; match_day() does the work (HU-37)."""
    rows = match_day(day, read_records(records_path), read_decisions(decisions_path, day))
    storage.write_jsonl(storage.join(output_path, "part-00000.json"), [to_json(r) for r in rows])
    matched = sum(1 for r in rows if r.status == MatchStatus.MATCHED.value)
    return {"day": day.isoformat(), "match_path": output_path,
            "matched": matched, "unmatched": len(rows) - matched}


def main(argv=None) -> None:  # spark-submit / EMR Serverless entry point
    """--day --records --decisions --output"""
    parser = argparse.ArgumentParser(description="Match a day of partner records with the decisions.")
    parser.add_argument("--day", required=True, type=date.fromisoformat)
    parser.add_argument("--records", required=True)
    parser.add_argument("--decisions", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(reconcile(None, args.day, args.records, args.decisions, args.output)))


if __name__ == "__main__":
    main()
