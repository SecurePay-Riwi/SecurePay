"""Swagger documentation of the cases API: summaries, descriptions and an
example of every status code. tests/test_openapi.py checks them.

Join point: each owner adds the constants of their endpoints here and
passes them as @router.<method>(..., **docs.NAME).
"""

from pydantic import BaseModel, Field

APP = {
    "title": "SecurePay cases API",
    "version": "1.0.0",
    "description": (
        "The cases an analyst works on: the inbox, assigning, resolving, "
        "the account history and the compliance reports. Cases are opened "
        "by the consumers from the engine's decisions (only the ones with "
        "`opens_case`) and escalated by the alerts task after 4 hours "
        "(RN-09).\n\n"
        "Send `X-User` with your name on every request that changes a case: "
        "it is the actor of the case event."
    ),
}


class Error(BaseModel):
    detail: str = Field(description="What went wrong.")


def _ok(description: str, example) -> dict:
    return {
        "description": description,
        "content": {"application/json": {"example": example}},
    }


def _error(description: str, detail: str) -> dict:
    return {
        "description": description,
        "model": Error,
        "content": {"application/json": {"example": {"detail": detail}}},
    }


DB_DOWN = _error("PostgreSQL is not available.", "The cases database is not available.")

HEALTH = {
    "summary": "Check that the API and its database are up",
    "tags": ["Health"],
    "responses": {200: _ok("Up.", {"status": "ok"}), 503: DB_DOWN},
}


# --- Compliance (HU-34) ------------------------------------------------------

_REPORT = {
    "id": "6f1c2b9e-3c1f-4a52-9a77-1e0f4f2d8c10",
    "case_id": "0b5e7c43-9d8a-4f6e-8f43-5a7d1c2e9b01",
    "transaction_id": "a3c1e5f7-2b4d-4c6e-8a0b-1d3f5a7c9e21",
    "account_id": "5d7f9b1c-3e5a-4c7e-9b1d-3f5a7c9e1b42",
    "document": "1000000070",
    "list_type": "PEP",
    "matched_at": "2026-10-31T14:02:11.418000Z",
    "notified_at": "2026-10-31T14:05:00.031000Z",
}

RESTRICTED_LIST_REPORTS = {
    "summary": "List the restricted list reports (RN-06)",
    "description": (
        "One report per listed document of a transaction: when the engine "
        "fires `restricted_list`, the cases consumer opens the case and "
        "writes a report for every owner of the source or destination "
        "account who is on the list. The alerts task e-mails the new ones "
        "to compliance every 5 minutes and sets `notified_at`.\n\n"
        "Newest first. `from` (inclusive) and `to` (exclusive) filter by "
        "`matched_at`; a date or time without a time zone is UTC. A period "
        "without reports is an empty list. Paginated with `page` and "
        "`size` (at most 100)."
    ),
    "responses": {
        200: _ok(
            "The reports of the period, newest first.",
            {"items": [_REPORT], "total": 1, "page": 1, "size": 50},
        ),
        400: _error(
            "A date is not valid, `from` is after `to`, or the page is out of range.",
            "The request contains invalid data.",
        ),
        503: DB_DOWN,
    },
}


# --- Reports (HU-35) --------------------------------------------------------

_SUSPICIOUS_CASE = {
    "case_id": "0b5e7c43-9d8a-4f6e-8f43-5a7d1c2e9b01",
    "transaction_id": "a3c1e5f7-2b4d-4c6e-8a0b-1d3f5a7c9e21",
    "account_id": "5d7f9b1c-3e5a-4c7e-9b1d-3f5a7c9e1b42",
    "pattern": "mule",
    "amount": "950000.00",
    "currency": "COP",
    "amount_usd": "230.05",
    "usd_rate": "4129.53",
    "rate_date": "2026-10-31",
    "status": "RESOLVED",
    "outcome": "FRAUD",
    "created_at": "2026-10-31T14:02:11.418000Z",
}

_SUSPICIOUS_CSV = (
    "case_id,transaction_id,account_id,pattern,amount,currency,amount_usd,status,outcome,created_at,"
    "usd_rate,rate_date\n"
    "0b5e7c43-9d8a-4f6e-8f43-5a7d1c2e9b01,a3c1e5f7-2b4d-4c6e-8a0b-1d3f5a7c9e21,"
    "5d7f9b1c-3e5a-4c7e-9b1d-3f5a7c9e1b42,mule,950000.00,COP,230.05,RESOLVED,FRAUD,"
    "2026-10-31T14:02:11.418000+00:00,4129.53,2026-10-31\n"
)

SUSPICIOUS_REPORT = {
    "summary": "Report the suspicious operations of a period",
    "description": (
        "The compliance cases opened in the period: mule account (RN-03), "
        "splitting (RN-05) and restricted list (RN-06), the decisions that "
        "open a case. One row per case with its account, `pattern` (the "
        "rules that fired, joined by `+`), the amount in the original "
        "currency (with its decimals: JPY has none) and in USD, with the "
        "rate the engine used (`usd_rate`, `rate_date`; RN-11), its state "
        "and its outcome, oldest first.\n\n"
        "`from` and `to` are days (`YYYY-MM-DD`, UTC), both inclusive, at "
        "most 31 days apart. `format=csv` returns the same rows as a file to "
        "download, `suspicious-report-<from>-<to>.csv`, with amounts as "
        "decimal text and `usd_rate`, `rate_date` as the last columns. A period without cases is an empty list with "
        "`message` (JSON) or only the header (CSV)."
    ),
    "responses": {
        200: {
            "description": "The cases of the period, as JSON or as a CSV file.",
            "content": {
                "application/json": {
                    "example": {
                        "from": "2026-10-31",
                        "to": "2026-10-31",
                        "items": [_SUSPICIOUS_CASE],
                        "total": 1,
                        "message": None,
                    },
                },
                "text/csv": {"example": _SUSPICIOUS_CSV},
            },
        },
        400: _error(
            "A date is missing or not valid, `from` is after `to`, the period has more "
            "than 31 days, or `format` is not json or csv.",
            "The period can have at most 31 days.",
        ),
        503: DB_DOWN,
    },
}


# --- Accounts (HU-28) --------------------------------------------------------

_ACCOUNT = "5d7f9b1c-3e5a-4c7e-9b1d-3f5a7c9e1b42"

_ACCOUNT_TRANSACTION = {
    "transaction_id": "a3c1e5f7-2b4d-4c6e-8a0b-1d3f5a7c9e21",
    "direction": "OUT",
    "counterparty_account_id": "9e1b3d5f-7a9c-4e1b-8d3f-5a7c9e1b3d64",
    "type": "P2P",
    "channel": "APP",
    "merchant_id": None,
    "amount": "950000.00",
    "currency": "COP",
    "amount_usd": "230.05",
    "usd_rate": "4129.53",
    "rate_date": "2026-10-31",
    "device_id": "c7e9a1b3-5d7f-4a9c-9e1b-3d5f7a9c1e86",
    "decision": "HOLD",
    "decision_reason": "More than 5 outgoing transfers in 10 minutes.",
    "rules_triggered": ["velocity"],
    "risk_score": 40,
    "transaction_date": "2026-10-31T13:58:40Z",
    "processed_at": "2026-10-31T13:58:40.112000Z",
}

ACCOUNT_TRANSACTIONS = {
    "summary": "List the last 30 days of an account's transactions",
    "description": (
        "Every transaction where the account took part in the last `days` "
        "days (at most 30, `ACCOUNT_HISTORY_DAYS`), whatever the engine "
        "decided: `OUT` when it was the source, `IN` when it was the "
        "destination. The amount is in the account's currency (JPY without "
        "decimals), with the engine's `amount_usd` and the rate behind it, "
        "`usd_rate` and `rate_date` (RN-11, HU-43). `device_id` is only on the main "
        "account's row (the source; in a top-up, the destination).\n\n"
        "Newest first by `transaction_date`. An account without history is "
        "an empty list. Paginated with `page` and `size` (at most 100). "
        "The history consumer writes it a moment after the decision, and "
        "the alerts task deletes what is older than 30 days."
    ),
    "responses": {
        200: _ok(
            "The account's transactions in the window, newest first.",
            {
                "account_id": _ACCOUNT,
                "days": 30,
                "items": [_ACCOUNT_TRANSACTION],
                "total": 1,
                "page": 1,
                "size": 50,
            },
        ),
        400: _error(
            "The account id is not a UUID, or `days`, `page` or `size` is out of range.",
            "The request contains invalid data.",
        ),
        503: DB_DOWN,
    },
}


# --- Accounts (HU-29) --------------------------------------------------------

RELATED_ACCOUNTS = {
    "summary": "List the accounts that shared a device with an account",
    "description": (
        "The devices the account used in the last `days` days (at most 30, "
        "`ACCOUNT_HISTORY_DAYS`) and the other accounts that used any of "
        "them in the same window, read from the account history "
        "(`device_id`, only on the main account's row: the source; in a "
        "top-up, the destination). It is the network behind the shared "
        "device rule (RN-04).\n\n"
        "One item per related account and shared device: an account that "
        "used two of the devices appears twice. `last_seen` is the related "
        "account's last transaction on that device; `open_cases` counts its "
        "cases that are `OPEN` or `ESCALATED`. The latest seen first. An "
        "account without devices in the window, or without related "
        "accounts, is an empty list."
    ),
    "responses": {
        200: _ok(
            "The related accounts, the latest seen first.",
            {
                "account_id": _ACCOUNT,
                "days": 30,
                "items": [
                    {
                        "account_id": "9e1b3d5f-7a9c-4e1b-8d3f-5a7c9e1b3d64",
                        "device_id": "c7e9a1b3-5d7f-4a9c-9e1b-3d5f7a9c1e86",
                        "last_seen": "2026-10-31T12:20:05Z",
                        "open_cases": 1,
                    }
                ],
                "total": 1,
            },
        ),
        400: _error(
            "The account id is not a UUID, or `days` is out of range.",
            "The request contains invalid data.",
        ),
        503: DB_DOWN,
    },
}


# --- Cases (HU-26) -----------------------------------------------------------

_CASE_ID = "0b5e7c43-9d8a-4f6e-8f43-5a7d1c2e9b01"

_CASE_SUMMARY = {
    "id": _CASE_ID,
    "transaction_id": "a3c1e5f7-2b4d-4c6e-8a0b-1d3f5a7c9e21",
    "account_id": "5d7f9b1c-3e5a-4c7e-9b1d-3f5a7c9e1b42",
    "status": "OPEN",
    "decision": "HOLD",
    "rules_triggered": ["mule"],
    "risk_score": 50,
    "amount": "950000.00",
    "currency": "COP",
    "amount_usd": "230.05",
    "usd_rate": "4129.53",
    "rate_date": "2026-10-31",
    "assignee": None,
    "created_at": "2026-10-31T14:02:11.418000Z",
    "due_at": "2026-10-31T18:02:11.418000Z",
    "minutes_left": 87,
}

_CASE_DETAIL = {
    **_CASE_SUMMARY,
    "decision_reason": "The account received 3 transfers from different senders and withdrew 95% of its balance.",
    "rules_version": "3",
    "rule_versions": {"mule": 1},
    "transaction_date": "2026-10-31T14:02:10Z",
    "transaction": {
        "id": "a3c1e5f7-2b4d-4c6e-8a0b-1d3f5a7c9e21",
        "type": "RETIRO",
        "source_account_id": "5d7f9b1c-3e5a-4c7e-9b1d-3f5a7c9e1b42",
        "destination_account_id": None,
        "amount": "950000.00",
        "currency": "COP",
        "transaction_date": "2026-10-31T14:02:10Z",
    },
    "escalated_at": None,
    "resolved_at": None,
    "resolved_by": None,
    "outcome": None,
    "final_decision": None,
    "resolution_note": None,
    "evidence_key": None,
    "events": [
        {
            "id": 1,
            "type": "CREATED",
            "actor": "system",
            "at": "2026-10-31T14:02:11.418000Z",
            "data": {},
        }
    ],
}

CASE_NOT_FOUND = _error("There is no case with that id.", "Case not found.")

CASES = {
    "summary": "List the case inbox",
    "description": (
        "The cases an analyst has to work on. Without `status`, the pending "
        "ones: `OPEN` and `ESCALATED` (still open after the 4-hour limit, "
        "RN-09). `status` asks for one state (`RESOLVED` too) and "
        "`assignee` for one analyst's cases.\n\n"
        "Highest `risk_score` first and, with the same risk, the closest to "
        "`due_at`. `minutes_left` is the whole minutes until `due_at`, "
        "negative once it is overdue, and null for a resolved case. "
        "Paginated with `page` and `size` (default 20, at most 100)."
    ),
    "responses": {
        200: _ok(
            "The cases of the page, by risk and then by time left.",
            {"items": [_CASE_SUMMARY], "total": 1, "page": 1, "size": 20},
        ),
        400: _error(
            "`status` is not a case state, or `assignee`, `page` or `size` is out of range.",
            "The request contains invalid data.",
        ),
        503: DB_DOWN,
    },
}

CASE = {
    "summary": "Read a case with its events",
    "description": (
        "Everything the case stores (the engine's decision, the transaction "
        "as it came, the resolution and the evidence key) and its events, "
        "oldest first: `CREATED`, `ASSIGNED`, `ESCALATED`, `RESOLVED`, "
        "`EVIDENCE_ARCHIVED`."
    ),
    "responses": {
        200: _ok("The case and its events.", _CASE_DETAIL),
        400: _error("The case id is not a UUID.", "The request contains invalid data."),
        404: CASE_NOT_FOUND,
        503: DB_DOWN,
    },
}


# --- Cases (HU-27) -----------------------------------------------------------

CASE_RESOLVED = _error(
    "The case is RESOLVED, which is final.",
    "The case is resolved; it can no longer change.",
)

_ASSIGNED_CASE = {
    **_CASE_DETAIL,
    "assignee": "ana",
    "events": [
        *_CASE_DETAIL["events"],
        {
            "id": 2,
            "type": "ASSIGNED",
            "actor": "supervisor.luis",
            "at": "2026-10-31T14:10:45.002000Z",
            "data": {"from": None, "to": "ana"},
        },
    ],
}

ASSIGN = {
    "summary": "Assign or reassign a case",
    "description": (
        "Sets the analyst who owns the case and writes an `ASSIGNED` event "
        "with the previous and the new owner (`from` is null the first "
        "time), with `X-User` as its actor. Assigning the owner it already "
        "has changes nothing and writes no event. An `ESCALATED` case can "
        "still be assigned; a `RESOLVED` one cannot (`409`).\n\n"
        "`X-User` is required. Returns the case with its events."
    ),
    "responses": {
        200: _ok("The case with its new owner and events.", _ASSIGNED_CASE),
        400: _error(
            "`X-User` is missing, the id is not a UUID, or `assignee` is not 1 to 100 characters.",
            "X-User must have 1 to 100 characters.",
        ),
        404: CASE_NOT_FOUND,
        409: CASE_RESOLVED,
        503: DB_DOWN,
    },
}


# --- Cases (HU-30) -----------------------------------------------------------

_RESOLVED_CASE = {
    **_ASSIGNED_CASE,
    "status": "RESOLVED",
    "minutes_left": None,
    "resolved_at": "2026-10-31T15:31:02.540000Z",
    "resolved_by": "ana",
    "outcome": "FRAUD",
    "final_decision": "REJECT",
    "resolution_note": "The three senders are linked accounts; the customer did not recognise the withdrawal.",
    "evidence_key": f"cases/2026/10/{_CASE_ID}.json",
    "events": [
        *_ASSIGNED_CASE["events"],
        {
            "id": 3,
            "type": "RESOLVED",
            "actor": "ana",
            "at": "2026-10-31T15:31:02.540000Z",
            "data": {
                "outcome": "FRAUD",
                "final_decision": "REJECT",
                "note": "The three senders are linked accounts; the customer did not recognise the withdrawal.",
            },
        },
        {
            "id": 4,
            "type": "EVIDENCE_ARCHIVED",
            "actor": "system",
            "at": "2026-10-31T15:31:02.871000Z",
            "data": {
                "bucket": "pagoseguro-evidence",
                "key": f"cases/2026/10/{_CASE_ID}.json",
                "retain_until": "2036-10-28T15:31:02.871000+00:00",
            },
        },
    ],
}

RESOLVE = {
    "summary": "Resolve a case with its outcome",
    "description": (
        "Closes the case: `FRAUD` sets `final_decision` to `REJECT` and "
        "`LEGITIMATE` to `APPROVE`. That is how the held transaction is "
        "rejected or released: there is no core to call (team decision "
        "D4), so the core reads `final_decision` from the case. Stores the "
        "outcome, the note, `resolved_at` and `resolved_by` (`X-User`) and "
        "writes a `RESOLVED` event, all in one transaction. The outcome "
        "feeds the rule precision and false-positive metrics.\n\n"
        "Then the evidence is archived for 10 years (RN-12) and its key is "
        "`evidence_key`. If archiving fails the case stays resolved, "
        "`evidence_key` is null and the alerts task retries it.\n\n"
        "An `OPEN` or `ESCALATED` case can be resolved, with or without an "
        "owner; a `RESOLVED` one cannot (`409`). `X-User` is required. "
        "Returns the case with its events."
    ),
    "responses": {
        200: _ok("The resolved case with its events.", _RESOLVED_CASE),
        400: _error(
            "`X-User` is missing, the id is not a UUID, `outcome` is not FRAUD or "
            "LEGITIMATE, or `note` is not 1 to 2000 characters.",
            "X-User must have 1 to 100 characters.",
        ),
        404: CASE_NOT_FOUND,
        409: CASE_RESOLVED,
        503: DB_DOWN,
    },
}


# --- Reconciliation differences (HU-38 to HU-41) ---------------------------

_DIFFERENCE = {
    "id": "3b9d1f57-2c4e-4a6b-8d0f-1e3a5c7e9b20",
    "run_day": "2026-10-05",
    "partner": "cajeros_express",
    "type": "AMOUNT_MISMATCH",
    "reference": "d462ba1c-5dab-599d-ac2e-63c354c7f3ce",
    "partner_reference": "CX000000002",
    "currency": "COP",
    "pagoseguro_amount": "123456.78",
    "partner_amount": "123457.00",
    "amount_difference": "0.22",
    "pagoseguro_at": "2026-10-05T19:00:00Z",
    "partner_at": "2026-10-05T19:00:00Z",
    "status": "PENDING",
    "age_days": 3,
    "detected_at": "2026-10-06T07:04:41.530000Z",
    "resolved_at": None,
    "resolved_by": None,
    "resolution_note": None,
}

_RESOLVED_DIFFERENCE = {
    **_DIFFERENCE,
    "status": "RESOLVED",
    "age_days": None,
    "resolved_at": "2026-10-08T15:12:09.004000Z",
    "resolved_by": "tesoreria.maria",
    "resolution_note": "The ATM network rounds COP to whole pesos; adjusted in the partner's next settlement.",
}

DIFFERENCE_NOT_FOUND = _error(
    "There is no difference with that id.", "Difference not found."
)

RECONCILIATION_DIFFERENCES = {
    "summary": "List the reconciliation differences (RN-10)",
    "description": (
        "What the nightly reconciliation could not match (RN-10: same "
        "reference, amount within 0.01, date within 1 day):\n\n"
        "- `MISSING_IN_PARTNER` (HU-38): PagoSeguro approved it and the "
        "partner's file does not have it. Only PagoSeguro's amount and time.\n"
        "- `MISSING_IN_PAGOSEGURO` (HU-39): it is in the partner's file and "
        "PagoSeguro did not approve it. Only the partner's amount, time and "
        "reference.\n"
        "- `AMOUNT_MISMATCH` (HU-40): same reference, more than 0.01 apart. "
        "Both amounts and `amount_difference` = partner − PagoSeguro.\n\n"
        "The same reference more than one day apart is missing on both "
        "sides (team decision D4). Amounts keep their currency's decimals "
        "(JPY: none).\n\n"
        "Without `status`, the `PENDING` ones; `type`, `partner` and `from`/"
        "`to` (days, inclusive, by `run_day`) narrow them. Oldest `run_day` "
        "first, then by partner. `age_days` counts whole days from "
        "`run_day` to today in UTC, null once resolved. Paginated with "
        "`page` and `size` (default 50, at most 200)."
    ),
    "responses": {
        200: _ok(
            "The differences of the page, oldest day first.",
            {"items": [_DIFFERENCE], "total": 1, "page": 1, "size": 50},
        ),
        400: _error(
            "`type`, `partner` or `status` is not a known value, a day is not valid, "
            "`from` is after `to`, or `page` or `size` is out of range.",
            "The request contains invalid data.",
        ),
        503: DB_DOWN,
    },
}

RECONCILIATION_AGING = {
    "summary": "Group the pending differences by age (HU-41)",
    "description": (
        "The `PENDING` differences by age in days (from `run_day` to today "
        "in UTC): `0-1`, `2-7` and `8+`. Always the three ranges, in that "
        "order, even when one is empty, each with its count by type. "
        "`partner` narrows it to one partner."
    ),
    "responses": {
        200: _ok(
            "The pending differences by age range.",
            {
                "total": 6,
                "ranges": [
                    {
                        "range": "0-1",
                        "count": 2,
                        "by_type": {
                            "MISSING_IN_PARTNER": 1,
                            "MISSING_IN_PAGOSEGURO": 1,
                            "AMOUNT_MISMATCH": 0,
                        },
                    },
                    {
                        "range": "2-7",
                        "count": 3,
                        "by_type": {
                            "MISSING_IN_PARTNER": 2,
                            "MISSING_IN_PAGOSEGURO": 0,
                            "AMOUNT_MISMATCH": 1,
                        },
                    },
                    {
                        "range": "8+",
                        "count": 1,
                        "by_type": {
                            "MISSING_IN_PARTNER": 0,
                            "MISSING_IN_PAGOSEGURO": 1,
                            "AMOUNT_MISMATCH": 0,
                        },
                    },
                ],
            },
        ),
        400: _error(
            "`partner` is not a known partner.", "The request contains invalid data."
        ),
        503: DB_DOWN,
    },
}

RECONCILIATION_RESOLVE = {
    "summary": "Resolve a reconciliation difference (HU-41)",
    "description": (
        "Treasury closes a difference with a note (1 to 2000 characters): it "
        "becomes `RESOLVED` with `resolved_at`, `resolved_by` (`X-User`) and "
        "`resolution_note`, and stops counting as pending. `RESOLVED` is "
        "final: running the day again never reopens it, and resolving it "
        "again is `409`.\n\n"
        "`X-User` is required. Returns the difference."
    ),
    "responses": {
        200: _ok("The resolved difference.", _RESOLVED_DIFFERENCE),
        400: _error(
            "`X-User` is missing, the id is not a UUID, or `note` is not 1 to 2000 characters.",
            "X-User must have 1 to 100 characters.",
        ),
        404: DIFFERENCE_NOT_FOUND,
        409: _error(
            "The difference is RESOLVED, which is final.",
            "The difference is resolved; it can no longer change.",
        ),
        503: DB_DOWN,
    },
}


# --- Reconciliation runs (HU-37) --------------------------------------------

_RUN = {
    "run_day": "2026-10-05",
    "status": "DONE",
    "started_at": "2026-10-06T07:00:02.118000Z",
    "finished_at": "2026-10-06T07:04:41.530000Z",
    "files_read": 4,
    "records_read": 11,
    "rows_rejected": 2,
    "matched": 8,
    "differences": 6,
    "error": None,
}

RECONCILIATION_RUNS = {
    "summary": "List the reconciliation runs of a period (RN-10)",
    "description": (
        "One run per partners' day: the nightly reconciliation reads the "
        "four partners' files, matches them with the approved transactions "
        "by reference, amount (±0.01) and date (±1 day) and stores the "
        "differences. A day run again updates its run.\n\n"
        "Oldest day first. `from` and `to` are days (`YYYY-MM-DD`), both "
        "inclusive, by `run_day`; without them, every run. A FAILED run "
        "says the step and its error in `error`."
    ),
    "responses": {
        200: _ok(
            "The runs of the period, oldest day first.", {"items": [_RUN], "total": 1}
        ),
        400: _error(
            "A day is not valid, or `from` is after `to`.",
            "The request contains invalid data.",
        ),
        503: DB_DOWN,
    },
}


# --- Senders of a case (CA-02) ---------------------------------------------

CASE_SENDERS = {
    "summary": "List the senders behind a case (the mule network)",
    "description": (
        "CA-02: the accounts that sent P2P transfers to the case's account "
        "in the `minutes` before the case's transaction (by default 30, the "
        "window of the mule rule, RN-03), read from the account history "
        "(the `IN` rows). One item per sender with how many transfers, "
        "their sum in USD, the first and the last, and the sender's own "
        "open cases; the most transfers first.\n\n"
        "`received_usd` adds every transfer of the window and "
        "`case_vs_received_pct` compares the case's transaction (in a mule "
        "case, the withdrawal) with it. The engine decides with the "
        "account's balance (`source_balance_before`), so this percentage "
        "explains the case but is not the rule's own number. A case "
        "without transfers before it is an empty list."
    ),
    "responses": {
        200: _ok(
            "The senders in the window, the most transfers first.",
            {
                "case_id": "0b5e7c43-9d8a-4f6e-8f43-5a7d1c2e9b01",
                "account_id": _ACCOUNT,
                "minutes": 30,
                "since": "2026-10-31T13:32:11Z",
                "until": "2026-10-31T14:02:11Z",
                "senders": [
                    {
                        "account_id": "9e1b3d5f-7a9c-4e1b-8d3f-5a7c9e1b3d64",
                        "transfers": 2,
                        "amount_usd": "120.40",
                        "first_at": "2026-10-31T13:40:02Z",
                        "last_at": "2026-10-31T13:51:47Z",
                        "open_cases": 0,
                    },
                    {
                        "account_id": "1f3a5c7e-9b1d-4f3a-8c5e-7a9c1e3b5d02",
                        "transfers": 1,
                        "amount_usd": "70.10",
                        "first_at": "2026-10-31T13:45:30Z",
                        "last_at": "2026-10-31T13:45:30Z",
                        "open_cases": 1,
                    },
                    {
                        "account_id": "7c9e1b3d-5f7a-4c9e-9b3d-5f7a9c1e3b28",
                        "transfers": 1,
                        "amount_usd": "65.00",
                        "first_at": "2026-10-31T13:58:12Z",
                        "last_at": "2026-10-31T13:58:12Z",
                        "open_cases": 0,
                    },
                ],
                "total_senders": 3,
                "received_usd": "255.50",
                "case_amount_usd": "230.05",
                "case_vs_received_pct": "90.04",
            },
        ),
        400: _error(
            "The case id is not a UUID, or `minutes` is out of range.",
            "The request contains invalid data.",
        ),
        404: CASE_NOT_FOUND,
        503: DB_DOWN,
    },
}
