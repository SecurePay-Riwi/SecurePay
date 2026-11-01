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
    return {"description": description, "content": {"application/json": {"example": example}}}


def _error(description: str, detail: str) -> dict:
    return {"description": description, "model": Error,
            "content": {"application/json": {"example": {"detail": detail}}}}


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
        400: _error("A date is not valid, `from` is after `to`, or the page is out of range.",
                    "The request contains invalid data."),
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
        "destination. The amount is in the account's currency, with the "
        "engine's `amount_usd` (RN-11). `device_id` is only on the main "
        "account's row (the source; in a top-up, the destination).\n\n"
        "Newest first by `transaction_date`. An account without history is "
        "an empty list. Paginated with `page` and `size` (at most 100). "
        "The history consumer writes it a moment after the decision, and "
        "the alerts task deletes what is older than 30 days."
    ),
    "responses": {
        200: _ok(
            "The account's transactions in the window, newest first.",
            {"account_id": _ACCOUNT, "days": 30, "items": [_ACCOUNT_TRANSACTION],
             "total": 1, "page": 1, "size": 50},
        ),
        400: _error("The account id is not a UUID, or `days`, `page` or `size` is out of range.",
                    "The request contains invalid data."),
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
                "items": [{
                    "account_id": "9e1b3d5f-7a9c-4e1b-8d3f-5a7c9e1b3d64",
                    "device_id": "c7e9a1b3-5d7f-4a9c-9e1b-3d5f7a9c1e86",
                    "last_seen": "2026-10-31T12:20:05Z",
                    "open_cases": 1,
                }],
                "total": 1,
            },
        ),
        400: _error("The account id is not a UUID, or `days` is out of range.",
                    "The request contains invalid data."),
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
    "events": [{
        "id": 1,
        "type": "CREATED",
        "actor": "system",
        "at": "2026-10-31T14:02:11.418000Z",
        "data": {},
    }],
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
        400: _error("`status` is not a case state, or `assignee`, `page` or `size` is out of range.",
                    "The request contains invalid data."),
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

CASE_RESOLVED = _error("The case is RESOLVED, which is final.",
                       "The case is resolved; it can no longer change.")

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
        400: _error("`X-User` is missing, the id is not a UUID, or `assignee` is not 1 to 100 characters.",
                    "X-User must have 1 to 100 characters."),
        404: CASE_NOT_FOUND,
        409: CASE_RESOLVED,
        503: DB_DOWN,
    },
}
